"""
TTSManager — point de contact unique entre l'orchestrateur et le TTS.

Gère le cycle de vie complet :
  NOT_INSTALLED → INSTALLED (pip ok, model ok) → LOADED (model en mémoire, prêt)

Même pattern que SoundManager : instancié dans Orchestrator.__init__(),
un seul objet pour toute la durée de vie de l'app.
"""

import logging
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

from .base import TTSEngine, TTSResult, VoiceInfo
from .chatterbox_tts import (
    ChatterboxTTS,
    ENGINE_ID as CHATTERBOX_ID,
    ENGINE_META as CHATTERBOX_META,
    _mtl_chunk_text,
    is_chatterbox_speech_supported,
    is_pip_installed as chatterbox_pip_ok,
    normalize_speech_lang,
)
from .installer import TTSInstaller
from .pytorch_cuda import nvidia_gpu_likely_present, pytorch_pip_index_url, torch_gpu_runs_basic_kernels
from .omnivoice_tts import (
    OmniVoiceTTS,
    ENGINE_ID as OMNIVOICE_ID,
    ENGINE_META as OMNIVOICE_META,
    is_pip_installed as omnivoice_pip_ok,
)
from .tag_sanitize import (
    sanitize_text_for_tts_engine,
    shield_paralinguistic_tags_for_tts_chunking,
)
from .voice_sample_paths import resolve_voice_sample_wav
from .model_registry import TTSModelRegistry

try:
    from utils.skin_paths import iter_voice_ref_pack_dirs
except ImportError:
    from App.utils.skin_paths import iter_voice_ref_pack_dirs

logger = logging.getLogger("perkysue.tts")

# ─── Install states (for GUI) ────────────────────────────────
INSTALL_NOT_INSTALLED = "not_installed"
INSTALL_INSTALLING = "installing"
INSTALL_INSTALLED = "installed"        # pip + model ok, but not loaded into memory yet
INSTALL_LOADED = "loaded"              # model in GPU/CPU memory, ready to speak

# Playback backend
_SD_AVAILABLE = False
_SD_IMPORT_WARNED = False
try:
    import sounddevice as sd
    import numpy as np
    _SD_AVAILABLE = True
except ImportError:
    sd = None
    np = None


def _engine_pip_ok(engine_id: str) -> bool:
    if engine_id == CHATTERBOX_ID:
        return chatterbox_pip_ok()
    if engine_id == OMNIVOICE_ID:
        return omnivoice_pip_ok()
    return False


class TTSManager:
    """Gestionnaire TTS pour PerkySue — feature Pro, opt-in."""

    KNOWN_ENGINES: Dict[str, dict] = {
        CHATTERBOX_ID: CHATTERBOX_META,
        OMNIVOICE_ID: OMNIVOICE_META,
    }

    def __init__(self, models_dir: Path, cache_dir: Path, paths):
        """
        Args:
            models_dir: Data/Models/TTS/
            cache_dir: Data/HuggingFace/
            paths: Objet Paths global
        """
        self.models_dir = models_dir
        self.cache_dir = cache_dir
        self.paths = paths
        self.model_registry = TTSModelRegistry(
            paths=paths,
            models_tts_dir=models_dir,
            hf_cache_dir=cache_dir,
            app_version="",
        )

        # Config (stored in Data/Configs/config.yaml under "tts:" key)
        self.enabled: bool = True
        self.auto_speak: bool = True
        self.volume: float = 0.8
        self.speed: float = 1.0
        self.trigger_modes: List[str] = ["answer", "help"]
        self.default_voice_id: Optional[str] = None

        self.preferred_engine_id: str = CHATTERBOX_ID
        # OmniVoice: we currently ship clone-only (design mode UI is hidden until ready).
        self.omnivoice_mode: str = "clone"
        self.omnivoice_instruct: str = "female, neutral pitch"
        self.omnivoice_num_step: int = 32
        self.omnivoice_repo: str = "k2-fsa/OmniVoice"

        # Engine state
        self._active_engine: Optional[TTSEngine] = None
        self._active_engine_id: Optional[str] = None
        self._install_state: str = INSTALL_NOT_INSTALLED

        # Installer
        python_exe = TTSInstaller.detect_python_exe()
        self.installer = TTSInstaller(python_exe, models_dir, cache_dir)

        # Voice packs (discovered from Data/Skins/)
        self._voice_packs: List[VoiceInfo] = []

        # Playback
        self._playback_lock = threading.Lock()
        self._is_speaking = False
        self._stop_requested = False
        # PCM → GUI: bipolar level [-1, 1] smoothed (sortie TTS + entrée micro)
        self._meter_lock = threading.Lock()
        self._meter_smoothed: float = 0.0  # playback
        self._meter_input_smoothed: float = 0.0  # microphone

        # Last failed engine load (stops Voice tab from auto-retrying in a tight loop)
        self._engine_load_error: Optional[str] = None
        self._model_registry_last_reason: str = ""

        # PyTorch CUDA offer (CPU-only torch + NVIDIA + Chatterbox/OmniVoice)
        self.pytorch_cuda_offer_never: bool = False
        self._pytorch_cuda_install_recommended: bool = False
        self._pytorch_cuda_install_index_url: Optional[str] = None

        # Voice payload layout (<PS_PAYLOAD>…) — see App/configs/voice_modes.yaml
        self.voice_payload_enabled: bool = True
        self.read_aloud_payload: bool = False

        # Active UI skin id for ``audios/voice_sample/voice_sample.wav`` (or ``voice_ref.wav``)
        self._tts_skin_id: str = "Default"

        self._detect_install_state()

        logger.info(
            "TTSManager: engine=%s state=%s, sd=%s",
            self.preferred_engine_id,
            self._install_state,
            "yes" if _SD_AVAILABLE else "NO",
        )

    def run_startup_maintenance(self) -> Dict[str, str]:
        """Migrate/create deterministic manifests from existing local HF cache."""
        out: Dict[str, str] = {}
        for engine_id in (CHATTERBOX_ID, OMNIVOICE_ID):
            ok, reason = self.model_registry.validate_entry(engine_id)
            if ok:
                out[engine_id] = "ok"
                continue
            fallback = self.omnivoice_repo if engine_id == OMNIVOICE_ID else None
            mig_ok, mig_reason = self.model_registry.refresh_from_cache(
                engine_id=engine_id,
                fallback_repo=fallback,
                reason=f"startup_migration:{reason}",
                local_files_only=True,
            )
            out[engine_id] = "migrated" if mig_ok else f"missing:{mig_reason}"
            if not mig_ok:
                logger.info("TTS model registry [%s]: %s", engine_id, mig_reason)
        return out

    def get_model_registry_status(self) -> Dict:
        return self.model_registry.status()

    # ─── Config integration ───────────────────────────────────

    def load_config(self, tts_config: dict):
        """Load TTS settings from the merged app config (config.yaml "tts:" section)."""
        if not tts_config:
            return
        self.enabled = tts_config.get("enabled", True)
        self.auto_speak = tts_config.get("auto_speak", True)
        self.volume = max(0.0, min(1.0, tts_config.get("volume", 0.8)))
        self.speed = max(0.25, min(3.0, tts_config.get("speed", 1.0)))
        self.trigger_modes = tts_config.get("trigger_modes", ["answer", "help"])
        self.default_voice_id = tts_config.get("default_voice")

        eng = (tts_config.get("engine") or CHATTERBOX_ID)
        eng = str(eng).strip().lower()
        if eng == "auto":
            eng = OMNIVOICE_ID if nvidia_gpu_likely_present() else CHATTERBOX_ID
        if eng in self.KNOWN_ENGINES:
            self.preferred_engine_id = eng
        else:
            self.preferred_engine_id = CHATTERBOX_ID

        # Force clone-only for now (design mode deprecated/hidden).
        self.omnivoice_mode = "clone"
        self.omnivoice_instruct = str(tts_config.get("omnivoice_instruct") or self.omnivoice_instruct)
        try:
            self.omnivoice_num_step = int(tts_config.get("omnivoice_num_step", self.omnivoice_num_step))
        except (TypeError, ValueError):
            self.omnivoice_num_step = 32
        self.omnivoice_num_step = max(8, min(self.omnivoice_num_step, 64))
        repo = (tts_config.get("omnivoice_repo") or self.omnivoice_repo)
        self.omnivoice_repo = str(repo).strip() or "k2-fsa/OmniVoice"

        self.pytorch_cuda_offer_never = bool(tts_config.get("pytorch_cuda_offer_never", False))

        self.voice_payload_enabled = bool(tts_config.get("voice_payload_enabled", True))
        self.read_aloud_payload = bool(tts_config.get("read_aloud_payload", False))

        self._detect_install_state()

    def to_config_dict(self) -> dict:
        """Export current state for saving to config.yaml "tts:" section."""
        return {
            "enabled": self.enabled,
            "auto_speak": self.auto_speak,
            "volume": round(self.volume, 2),
            "speed": round(self.speed, 2),
            "trigger_modes": list(self.trigger_modes),
            "default_voice": self.default_voice_id,
            "engine": self.preferred_engine_id,
            "omnivoice_mode": self.omnivoice_mode,
            "omnivoice_instruct": self.omnivoice_instruct,
            "omnivoice_num_step": self.omnivoice_num_step,
            "omnivoice_repo": self.omnivoice_repo,
            "pytorch_cuda_offer_never": self.pytorch_cuda_offer_never,
            "voice_payload_enabled": self.voice_payload_enabled,
            "read_aloud_payload": self.read_aloud_payload,
        }

    def _omnivoice_options(self) -> dict:
        return {
            "omnivoice_mode": self.omnivoice_mode,
            "omnivoice_instruct": self.omnivoice_instruct,
            "omnivoice_num_step": self.omnivoice_num_step,
            "omnivoice_repo": self.omnivoice_repo,
        }

    # ─── Install state ────────────────────────────────────────

    def _detect_install_state(self):
        if (
            self._active_engine
            and self._active_engine_id == self.preferred_engine_id
            and self._active_engine.is_available()
        ):
            self._install_state = INSTALL_LOADED
            return
        if _engine_pip_ok(self.preferred_engine_id):
            self._install_state = INSTALL_INSTALLED
        else:
            self._install_state = INSTALL_NOT_INSTALLED

    @property
    def install_state(self) -> str:
        if self.installer.is_running:
            return INSTALL_INSTALLING
        if self._active_engine and self._active_engine.is_available():
            return INSTALL_LOADED
        return self._install_state

    def is_installed(self) -> bool:
        if self._active_engine and self._active_engine.is_available():
            return True
        return _engine_pip_ok(self.preferred_engine_id)

    def is_loaded(self) -> bool:
        return self._active_engine is not None and self._active_engine.is_available()

    @property
    def engine_load_error(self) -> Optional[str]:
        return self._engine_load_error

    def clear_engine_load_error(self):
        """Allow another automatic or manual load attempt after a failure."""
        self._engine_load_error = None

    # ─── Engine lifecycle ─────────────────────────────────────

    def load_engine(self) -> bool:
        """Load the preferred engine into memory (warmup)."""
        self._engine_load_error = None
        if not _engine_pip_ok(self.preferred_engine_id):
            logger.warning("TTS load_engine: pip package missing for %s", self.preferred_engine_id)
            return False

        if (
            self._active_engine_id == self.preferred_engine_id
            and self._active_engine
            and self._active_engine.is_available()
        ):
            self._install_state = INSTALL_LOADED
            self._refresh_pytorch_cuda_install_offer(self._active_engine, self.preferred_engine_id)
            return True

        if self._active_engine:
            self._active_engine.unload()
            self._active_engine = None
            self._active_engine_id = None

        eid = self.preferred_engine_id
        try:
            fallback_repo = self.omnivoice_repo if eid == OMNIVOICE_ID else None
            ok_manifest, reason = self.model_registry.validate_entry(eid)
            if not ok_manifest:
                self._model_registry_last_reason = reason
                logger.info("TTS model registry invalid for %s: reason=%s", eid, reason)
                # Deterministic path first: do not network-fetch at boot.
                mig_ok, mig_reason = self.model_registry.refresh_from_cache(
                    engine_id=eid,
                    fallback_repo=fallback_repo,
                    reason=f"boot_repair:{reason}",
                    local_files_only=True,
                )
                if not mig_ok:
                    logger.warning(
                        "TTS model load blocked: engine=%s reason=%s repair=%s",
                        eid,
                        reason,
                        mig_reason,
                    )
                    self._engine_load_error = (
                        f"Model manifest invalid ({reason}) and no local snapshot available ({mig_reason}). "
                        "Open Voice tab and run Repair/Install."
                    )
                    logger.warning("TTS load blocked for %s: %s", eid, self._engine_load_error)
                    return False
            entry = self.model_registry.get_entry(eid) or {}
            local_snapshot = entry.get("resolved_snapshot")

            if eid == CHATTERBOX_ID:
                engine = ChatterboxTTS(
                    models_dir=self.models_dir / CHATTERBOX_ID,
                    cache_dir=self.cache_dir,
                    model_local_dir=Path(local_snapshot) if local_snapshot else None,
                    allow_online_fetch=False,
                )
                engine.warmup(paths=self.paths)
            elif eid == OMNIVOICE_ID:
                engine = OmniVoiceTTS(
                    models_dir=self.models_dir / OMNIVOICE_ID,
                    cache_dir=self.cache_dir,
                    get_options=self._omnivoice_options,
                    model_local_dir=Path(local_snapshot) if local_snapshot else None,
                    allow_online_fetch=False,
                )
                engine.warmup(paths=self.paths)
            else:
                logger.error("Unknown TTS engine: %s", eid)
                return False

            if engine.is_available():
                self._active_engine = engine
                self._active_engine_id = eid
                self._install_state = INSTALL_LOADED
                self._engine_load_error = None
                logger.info("TTS engine loaded: %s", eid)
                self._refresh_pytorch_cuda_install_offer(engine, eid)
                return True

            err = getattr(engine, "_warmup_error", None) or "Model did not load (warmup incomplete)"
            self._engine_load_error = err
            logger.warning("TTS engine warmup incomplete: %s", err)
            self._pytorch_cuda_install_recommended = False
            self._pytorch_cuda_install_index_url = None
            return False

        except Exception as e:
            self._engine_load_error = str(e)
            logger.error("TTS load_engine failed: %s", e)
            self._pytorch_cuda_install_recommended = False
            self._pytorch_cuda_install_index_url = None
            return False

    def _refresh_pytorch_cuda_install_offer(self, engine: TTSEngine, eid: str) -> None:
        """Offer pip PyTorch CUDA when CPU-only wheel, or CUDA wheel that cannot run kernels on this GPU (e.g. cu124 on RTX 5090)."""
        self._pytorch_cuda_install_recommended = False
        self._pytorch_cuda_install_index_url = None
        if self.pytorch_cuda_offer_never:
            return
        if eid not in (CHATTERBOX_ID, OMNIVOICE_ID):
            return
        idx = pytorch_pip_index_url()
        if not idx:
            return
        if getattr(engine, "_device", "") != "cpu":
            return
        built = getattr(engine, "_pytorch_cuda_built", None)
        if built is False:
            self._pytorch_cuda_install_recommended = True
            self._pytorch_cuda_install_index_url = idx
            return
        if built is True:
            try:
                import torch

                if torch.cuda.is_available() and not torch_gpu_runs_basic_kernels():
                    self._pytorch_cuda_install_recommended = True
                    self._pytorch_cuda_install_index_url = idx
            except Exception:
                pass

    def unload_engine(self):
        """Unload engine from memory (free VRAM)."""
        if self._active_engine:
            self._active_engine.unload()
            self._active_engine = None
            self._active_engine_id = None
        if _engine_pip_ok(self.preferred_engine_id):
            self._install_state = INSTALL_INSTALLED
        else:
            self._install_state = INSTALL_NOT_INSTALLED
        logger.info("TTS engine unloaded")

    def get_engine_meta(self) -> dict:
        eid = self._active_engine_id or self.preferred_engine_id
        return dict(self.KNOWN_ENGINES.get(eid, CHATTERBOX_META))

    def get_active_engine(self) -> Optional[TTSEngine]:
        return self._active_engine

    def will_block_for_multilingual_model(self, language: Optional[str]) -> bool:
        """True when Chatterbox will download/load MTL weights before the next non-English synth."""
        if self._active_engine_id != CHATTERBOX_ID:
            return False
        eng = self._active_engine
        if eng is None or not hasattr(eng, "will_download_or_load_multilingual"):
            return False
        return bool(eng.will_download_or_load_multilingual(language or "en"))

    # ─── Voice packs (from Data/Skins/) ───────────────────────

    def scan_voice_packs(self):
        """Discover voice ref audio files bundled with skins.

        Layout: ``Data/Skins/<Character>/<Locale>/voice_ref.wav`` (or legacy locale/character).
        Optional ``voice_ref.txt`` beside the wav. Samples: ``audios/voice_sample/voice_sample.wav`` (+ optional ``voice_sample.txt``).
        """
        self._voice_packs.clear()
        for skin_id, pack_dir in iter_voice_ref_pack_dirs(self.paths):
            ref_wav = pack_dir / "voice_ref.wav"
            if not ref_wav.is_file():
                continue
            char = skin_id.split("/", 1)[0]
            voice_id = char.strip().lower()
            ref_txt = pack_dir / "voice_ref.txt"
            ref_transcript = None
            if ref_txt.is_file():
                try:
                    ref_transcript = ref_txt.read_text(encoding="utf-8").strip() or None
                except OSError:
                    ref_transcript = None
            self._voice_packs.append(VoiceInfo(
                id=voice_id,
                name=char,
                source="cloned",
                ref_audio=str(ref_wav),
                ref_transcript=ref_transcript,
                skin_id=skin_id,
            ))
            logger.info("TTS voice pack: %s → %s", voice_id, ref_wav)

    def get_all_voices(self) -> List[VoiceInfo]:
        """All available voices: engine builtins + voice packs from skins."""
        voices = []
        if self._active_engine:
            voices.extend(self._active_engine.get_voices())
        voices.extend(self._voice_packs)
        return voices

    def _resolve_voice(self, voice_id: Optional[str]) -> Optional[VoiceInfo]:
        if not voice_id:
            voice_id = self.default_voice_id
        if not voice_id:
            return None
        for v in self.get_all_voices():
            if v.id == voice_id:
                return v
        return None

    def _voice_with_optional_lang_sample(
        self, voice_id: Optional[str], language: Optional[str]
    ) -> Optional[VoiceInfo]:
        """Prefer skin clone; else optional per-language WAV for timbre (Chatterbox + OmniVoice clone)."""
        v = self._resolve_voice(voice_id)
        if v and v.ref_audio and Path(v.ref_audio).is_file():
            return v
        sample = resolve_voice_sample_wav(self.paths, self._tts_skin_id, language)
        if sample and sample.is_file():
            ref_transcript = None
            txt = sample.with_suffix(".txt")
            if txt.is_file():
                try:
                    ref_transcript = txt.read_text(encoding="utf-8").strip() or None
                except OSError:
                    ref_transcript = None
            return VoiceInfo(
                id="_lang_sample",
                name="Language sample",
                ref_audio=str(sample),
                ref_transcript=ref_transcript,
                source="builtin",
            )
        return v

    def get_voice_for_skin(self, skin_name: str) -> Optional[VoiceInfo]:
        """Find voice linked to a skin."""
        for v in self._voice_packs:
            if v.skin_id and v.skin_id.lower() == skin_name.lower():
                return v
        skin_key = (
            skin_name.split("/", 1)[0].strip().lower()
            if "/" in skin_name
            else skin_name.lower()
        )
        for v in self._voice_packs:
            if skin_key in v.id:
                return v
        return None

    def on_skin_changed(self, skin_name: str):
        """Auto-switch voice when user changes skin."""
        # Keep the active skin in sync for `audios/voice_sample/voice_sample.wav` (or voice_ref.wav).
        self._tts_skin_id = (skin_name or "Default").strip() or "Default"
        voice = self.get_voice_for_skin(skin_name)
        if voice:
            self.default_voice_id = voice.id
            logger.info("TTS voice auto-linked: skin %s → voice %s", skin_name, voice.id)
        else:
            logger.info("TTS skin set: %s (no voice_ref / voice_sample.wav in resolved pack; engine default ref if any)", self._tts_skin_id)

    # ─── Speak / Stop ─────────────────────────────────────────

    def _ensure_torchcodec_for_omnivoice(self) -> bool:
        """OmniVoice uses torchaudio.load for reference audio. We patch local .wav to soundfile in warmup; else TorchCodec+FFmpeg may be needed."""
        if self._active_engine_id != OMNIVOICE_ID:
            return True
        from .omnivoice_tts import local_wav_torchaudio_patch_active

        if local_wav_torchaudio_patch_active():
            return True
        try:
            import torchcodec  # noqa: F401
            return True
        except Exception as e:
            logger.error(
                "OmniVoice: reference audio needs either .wav files (soundfile) or a working torchcodec build with FFmpeg on PATH. %s",
                e,
            )
            return False

    def is_spoken_language_supported(self, language: Optional[str]) -> bool:
        """Whether the active engine can speak this language (ISO-ish code or Whisper label)."""
        if self._active_engine_id != CHATTERBOX_ID:
            return True
        return is_chatterbox_speech_supported(language or "en")

    def prepare_speak(
        self,
        text: str,
        voice_id: Optional[str] = None,
        language: Optional[str] = None,
    ) -> Optional[TTSResult]:
        """Synthesize only (no playback). Used to align chat UI refresh with audio start."""
        if not self.enabled or not self.is_loaded():
            return None

        text = (text or "").strip()
        if not text:
            return None

        eid = (self._active_engine_id or self.preferred_engine_id or CHATTERBOX_ID).strip().lower()
        text = sanitize_text_for_tts_engine(text, self.paths, eid, language)
        if not text:
            return None
        text = shield_paralinguistic_tags_for_tts_chunking(text)

        lang_n = normalize_speech_lang(language)
        if self._active_engine_id == CHATTERBOX_ID and not is_chatterbox_speech_supported(lang_n):
            return None

        voice = self._voice_with_optional_lang_sample(voice_id, language)

        if not self._ensure_torchcodec_for_omnivoice():
            return None

        try:
            with self._playback_lock:
                self._stop_requested = False
            t0 = time.monotonic()
            synth_kw = {"text": text, "voice": voice, "language": language, "speed": self.speed}
            if self._active_engine_id == CHATTERBOX_ID:
                lang_n = normalize_speech_lang(language or "en")
                if lang_n != "en" and len(_mtl_chunk_text(text)) > 1:
                    synth_kw["mtl_chunk_audio_callback"] = self._play_raw_chunk_blocking
                    synth_kw["should_stop"] = (lambda: bool(self._stop_requested))
            result = self._active_engine.synthesize(**synth_kw)
            logger.info(
                "TTS prepare: %.1fs audio in %.2fs (RTF=%.3f)%s",
                result.duration,
                time.monotonic() - t0,
                result.rtf,
                " (chunks played during synth)" if getattr(result, "already_streamed", False) else "",
            )
            return result
        except Exception as e:
            logger.error("TTS prepare_speak failed: %s", e)
            return None

    def play_prepared(self, result: Optional[TTSResult], blocking: bool = False) -> None:
        """Play audio from :meth:`prepare_speak`."""
        if result is None:
            return
        if getattr(result, "already_streamed", False):
            return
        if blocking:
            self._play_audio_blocking(result)
        else:
            threading.Thread(target=self._play_audio_blocking, args=(result,), daemon=True).start()

    def speak(
        self,
        text: str,
        voice_id: Optional[str] = None,
        language: Optional[str] = None,
        blocking: bool = False,
    ) -> Optional[TTSResult]:
        """Synthesize and play text. Non-blocking by default."""
        if not self.enabled or not self.is_loaded():
            return None

        text = (text or "").strip()
        if not text:
            return None

        eid = (self._active_engine_id or self.preferred_engine_id or CHATTERBOX_ID).strip().lower()
        text = sanitize_text_for_tts_engine(text, self.paths, eid, language)
        if not text:
            return None
        text = shield_paralinguistic_tags_for_tts_chunking(text)

        lang_n = normalize_speech_lang(language)
        if self._active_engine_id == CHATTERBOX_ID and not is_chatterbox_speech_supported(lang_n):
            return None

        voice = self._voice_with_optional_lang_sample(voice_id, language)

        if not self._ensure_torchcodec_for_omnivoice():
            return None

        try:
            with self._playback_lock:
                self._stop_requested = False
            t0 = time.monotonic()
            synth_kw = {"text": text, "voice": voice, "language": language, "speed": self.speed}
            if self._active_engine_id == CHATTERBOX_ID:
                lang_n = normalize_speech_lang(language or "en")
                if lang_n != "en" and len(_mtl_chunk_text(text)) > 1:
                    synth_kw["mtl_chunk_audio_callback"] = self._play_raw_chunk_blocking
                    synth_kw["should_stop"] = (lambda: bool(self._stop_requested))
            result = self._active_engine.synthesize(**synth_kw)
            logger.info(
                "TTS: %.1fs audio in %.2fs (RTF=%.3f)%s",
                result.duration,
                time.monotonic() - t0,
                result.rtf,
                " (chunks played during synth)" if getattr(result, "already_streamed", False) else "",
            )

            if getattr(result, "already_streamed", False):
                return result
            if blocking:
                self._play_audio_blocking(result)
            else:
                threading.Thread(target=self._play_audio_blocking, args=(result,), daemon=True).start()
            return result

        except Exception as e:
            logger.error("TTS speak failed: %s", e)
            return None

    def _playback_reset_meter(self) -> None:
        with self._meter_lock:
            self._meter_smoothed = 0.0

    def _bipolar_raw_from_chunk(self, chunk) -> Optional[float]:
        """Raw bipolar estimate [-1, 1] from one float32 mono-ish block."""
        if not _SD_AVAILABLE:
            return None
        try:
            x = np.asarray(chunk, dtype=np.float32).flatten()
            if x.size == 0:
                return None
            rms = float(np.sqrt(np.mean(x * x)))
            mn = float(np.mean(x))
            ref_rms = 0.07
            ref_mean = 0.06
            sign = 1.0 if mn >= 0.0 else -1.0
            env = min(1.0, rms / max(1e-8, ref_rms))
            signed = sign * env
            mean_comp = float(np.clip(mn / max(1e-8, ref_mean), -1.0, 1.0))
            raw = 0.55 * signed + 0.45 * mean_comp
            return float(np.clip(raw, -1.0, 1.0))
        except Exception:
            return None

    def _playback_feed_meter(self, chunk) -> None:
        """Update smoothed bipolar level from one PCM block (TTS output)."""
        raw = self._bipolar_raw_from_chunk(chunk)
        if raw is None:
            return
        with self._meter_lock:
            prev = self._meter_smoothed
            # Lissage plus lent = modulation moins saccadée
            a = 0.35 if abs(raw) > abs(prev) else 0.16
            self._meter_smoothed = prev * (1.0 - a) + raw * a

    def input_feed_meter(self, chunk) -> None:
        """Update smoothed bipolar level from one PCM block (micro, même logique que la sortie)."""
        raw = self._bipolar_raw_from_chunk(chunk)
        if raw is None:
            return
        with self._meter_lock:
            prev = self._meter_input_smoothed
            a = 0.35 if abs(raw) > abs(prev) else 0.16
            self._meter_input_smoothed = prev * (1.0 - a) + raw * a

    def reset_input_meter(self) -> None:
        with self._meter_lock:
            self._meter_input_smoothed = 0.0

    @staticmethod
    def _ring_offset_from_t(t: float) -> int:
        off = int(round(float(t) * 9.0))
        return max(-9, min(9, off))

    def get_playback_ring_offset_px(self) -> int:
        with self._meter_lock:
            return self._ring_offset_from_t(self._meter_smoothed)

    def get_input_ring_offset_px(self) -> int:
        with self._meter_lock:
            return self._ring_offset_from_t(self._meter_input_smoothed)

    def get_avatar_ring_offset_px(self) -> int:
        """Alias = sortie TTS uniquement (compat)."""
        return self.get_playback_ring_offset_px()

    def _play_raw_chunk_blocking(self, audio, sample_rate: int) -> None:
        """Play one float32 mono chunk (Chatterbox MTL streaming). Respects volume and stop."""
        global _SD_IMPORT_WARNED
        if not _SD_AVAILABLE:
            if not _SD_IMPORT_WARNED:
                _SD_IMPORT_WARNED = True
                logger.warning(
                    "TTS chunk playback unavailable: sounddevice/numpy failed to import at startup — pip install sounddevice"
                )
            return
        if audio is None:
            return
        if self._stop_requested:
            return
        try:
            import numpy as np

            chunk = np.asarray(audio, dtype=np.float32).squeeze()
            if chunk.size == 0:
                return
            chunk = chunk * self.volume
        except Exception:
            return
        self._playback_feed_meter(chunk)
        with self._playback_lock:
            self._is_speaking = True
        try:
            sd.play(chunk, samplerate=int(sample_rate))
            while sd.get_stream() and sd.get_stream().active:
                if self._stop_requested:
                    sd.stop()
                    break
                time.sleep(0.05)
        except Exception as e:
            logger.error("TTS chunk playback error: %s", e)
        finally:
            with self._playback_lock:
                self._is_speaking = False

    def _play_audio_blocking(self, result: TTSResult):
        global _SD_IMPORT_WARNED
        if not _SD_AVAILABLE:
            if not _SD_IMPORT_WARNED:
                _SD_IMPORT_WARNED = True
                logger.warning(
                    "TTS playback unavailable: sounddevice/numpy failed to import at startup — pip install sounddevice"
                )
            return
        if result is None or result.audio is None:
            return

        import numpy as np

        with self._playback_lock:
            self._is_speaking = True
            self._stop_requested = False
        self._playback_reset_meter()
        try:
            audio = result.audio
            if hasattr(audio, "squeeze"):
                audio = audio.squeeze()
            if hasattr(audio, "astype"):
                audio = audio.astype(np.float32)
            if audio.ndim > 1:
                audio = np.asarray(audio[:, 0], dtype=np.float32)
            audio = np.ascontiguousarray(audio * self.volume, dtype=np.float32)
            sr = int(result.sample_rate)
            n = int(audio.shape[0])

            stream_ok = False
            if n > 0 and _SD_AVAILABLE:
                pos = 0
                blocksize = min(1024, max(256, n // 16 or 256))

                def callback(outdata, frames, time, status):
                    nonlocal pos
                    if self._stop_requested:
                        outdata.fill(0.0)
                        raise sd.CallbackStop
                    remaining = n - pos
                    if remaining <= 0:
                        outdata.fill(0.0)
                        raise sd.CallbackStop
                    take = min(frames, remaining)
                    sl = audio[pos : pos + take]
                    self._playback_feed_meter(sl)
                    if take < frames:
                        if outdata.ndim == 1:
                            outdata[:take] = sl
                            outdata[take:] = 0.0
                        else:
                            outdata[:take, 0] = sl
                            outdata[take:, 0] = 0.0
                        pos += take
                        raise sd.CallbackStop
                    if outdata.ndim == 1:
                        outdata[:] = sl
                    else:
                        outdata[:, 0] = sl
                    pos += take

                try:
                    with sd.OutputStream(
                        samplerate=sr,
                        channels=1,
                        dtype="float32",
                        blocksize=blocksize,
                        callback=callback,
                    ) as stream:
                        while stream.active:
                            if self._stop_requested:
                                try:
                                    sd.stop()
                                except Exception:
                                    pass
                                break
                            time.sleep(0.02)
                    stream_ok = True
                except Exception as ex:
                    logger.debug("TTS OutputStream playback failed, fallback to sd.play: %s", ex)

            if not stream_ok and n > 0:
                sd.play(audio, samplerate=sr)
                while sd.get_stream() and sd.get_stream().active:
                    if self._stop_requested:
                        sd.stop()
                        break
                    time.sleep(0.05)
        except Exception as e:
            logger.error("TTS playback error: %s", e)
        finally:
            with self._playback_lock:
                self._is_speaking = False
                self._stop_requested = False
            self._playback_reset_meter()

    def stop(self):
        # Best-effort hard stop: stop streaming synth + stop/abort playback backend.
        with self._playback_lock:
            self._stop_requested = True
            self._is_speaking = False
        self._playback_reset_meter()
        if not _SD_AVAILABLE:
            return
        # sounddevice can occasionally keep a stream in a bad state after abrupt cancellation;
        # try a couple of safe stop/abort paths.
        try:
            sd.stop()
        except Exception:
            pass
        try:
            st = sd.get_stream()
            if st:
                try:
                    st.abort()
                except Exception:
                    pass
                try:
                    st.close()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            # One more stop after abort/close to ensure the backend is quiet.
            sd.stop()
        except Exception:
            pass

    def is_speaking(self) -> bool:
        return self._is_speaking
