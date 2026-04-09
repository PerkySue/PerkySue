"""
Chatterbox Turbo engine — 350M params, MIT, voice cloning, emotion control.

Le package pip et le modèle se téléchargent à la demande via installer.py.
Ce fichier ne crash pas si chatterbox-tts n'est pas installé.
"""

import logging
import os
import re
import time
import inspect
from pathlib import Path
from typing import Any, Callable, List, Optional

from .base import TTSEngine, TTSResult, VoiceInfo
from .pytorch_cuda import torch_gpu_runs_basic_kernels

logger = logging.getLogger("perkysue.tts.chatterbox")


def _turbo_wav_sane(wav) -> bool:
    """True if Chatterbox Turbo ``generate()`` returned usable audio (non-empty, finite, not silent)."""
    if wav is None:
        return False
    try:
        import torch

        if not hasattr(wav, "numel"):
            return False
        if int(wav.numel()) < 32:
            return False
        x = wav.detach().float().cpu().reshape(-1)
        if x.numel() == 0:
            return False
        if not bool(torch.isfinite(x).all()):
            return False
        peak = float(torch.abs(x).max().item())
        if peak < 1e-7:
            return False
        return True
    except Exception:
        return False


def _resolve_chatterbox_torch_device(torch) -> str:
    """Choose cuda | mps | cpu. Set ``PERKYSUE_CHATTERBOX_DEVICE=cpu|cuda|mps`` to override auto."""
    raw = (os.environ.get("PERKYSUE_CHATTERBOX_DEVICE") or "").strip().lower()
    if raw == "cpu":
        return "cpu"
    if raw == "cuda":
        if not torch.cuda.is_available():
            return "cpu"
        return "cuda" if torch_gpu_runs_basic_kernels() else "cpu"
    if raw == "mps":
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
        return "cpu"
    if torch.cuda.is_available():
        if not torch_gpu_runs_basic_kernels():
            logger.warning(
                "Chatterbox: PyTorch reports CUDA but this GPU is not supported by the installed "
                "wheel (e.g. RTX 5090 / sm_120 vs cu124 build capped at sm_90). Using CPU for TTS; "
                "install PyTorch cu128 wheels (e.g. install_pytorch_cuda_cu128.bat) or see pytorch.org/get-started/locally/."
            )
            return "cpu"
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def clear_blank_cuda_visible_devices() -> None:
    """Undo ``CUDA_VISIBLE_DEVICES=''`` set by the LLM GPU probe in the same process.

    That env hides all GPUs from **PyTorch** (Chatterbox / OmniVoice) even when llama-server uses CUDA
    in a separate process. Remove only when the value is empty (meaning "hide all").
    """
    v = os.environ.get("CUDA_VISIBLE_DEVICES")
    if v is not None and str(v).strip() == "":
        del os.environ["CUDA_VISIBLE_DEVICES"]
        logger.info("Cleared empty CUDA_VISIBLE_DEVICES so PyTorch TTS can use CUDA.")


def dev_tts_diagnostics_enabled(paths: Optional[Any]) -> bool:
    """True when ``Data/Plugins/dev/manifest.yaml`` exists (same rule as orchestrator dev plugin folder)."""
    try:
        if paths is None:
            return False
        p = Path(paths.plugins) / "dev" / "manifest.yaml"
        return p.is_file()
    except Exception:
        return False


def log_tts_dev_device_diagnostics(
    paths: Optional[Any],
    phase: str,
    engine_label: str,
    chosen_device: Optional[str] = None,
) -> None:
    """Verbose PyTorch/CUDA state when dev plugin is present. Uses WARNING so default logs show it."""
    if not dev_tts_diagnostics_enabled(paths):
        return
    lines = [
        f"[DEV TTS] {engine_label} — phase={phase}",
        f"  CUDA_VISIBLE_DEVICES={os.environ.get('CUDA_VISIBLE_DEVICES', '<unset>')!r}",
        f"  PERKYSUE_BACKEND={os.environ.get('PERKYSUE_BACKEND', '<unset>')!r}",
    ]
    if chosen_device is not None:
        lines.append(f"  chosen_device={chosen_device!r}")
    try:
        import torch

        lines.append(f"  torch.__version__={torch.__version__}")
        lines.append(f"  torch.cuda.is_available()={torch.cuda.is_available()}")
        lines.append(f"  torch.backends.cuda.is_built()={torch.backends.cuda.is_built()}")
        lines.append(f"  torch.version.cuda={getattr(torch.version, 'cuda', None)!r}")
        if torch.cuda.is_available():
            try:
                n = torch.cuda.device_count()
                lines.append(f"  torch.cuda.device_count()={n}")
                if n > 0:
                    lines.append(f"  torch.cuda.get_device_name(0)={torch.cuda.get_device_name(0)!r}")
            except Exception as ex:
                lines.append(f"  cuda device query error: {ex}")
        else:
            try:
                built = bool(torch.backends.cuda.is_built())
            except Exception:
                built = False
            if not built:
                lines.append(
                    "  ROOT CAUSE: PyTorch wheel is CPU-only (torch.backends.cuda.is_built()=False). "
                    "Whisper may still use GPU via CTranslate2; Chatterbox/OmniVoice need CUDA-enabled PyTorch."
                )
                lines.append(
                    "  Fix (typical for PerkySue CUDA 12.4 backend): "
                    "Python\\python.exe -m pip install --upgrade torch torchvision torchaudio "
                    "--index-url https://download.pytorch.org/whl/cu124"
                )
            else:
                lines.append(
                    "  hint: CUDA built in PyTorch but not available — check CUDA_VISIBLE_DEVICES before "
                    "first torch import, driver, and GPU visibility."
                )
    except Exception as e:
        lines.append(f"  torch import/check failed: {type(e).__name__}: {e}")
    logger.warning("\n".join(lines))


# Chatterbox MTL hard-codes max_new_tokens=1000 speech tokens per generate() call (see chatterbox/mtl_tts.py).
# Long replies hit that ceiling → truncated / unstable audio while the UI shows the full LLM text.
_MTL_CHUNK_CHARS_DEFAULT = 280


def _mtl_chunk_text(text: str, max_chars: int = _MTL_CHUNK_CHARS_DEFAULT) -> List[str]:
    """Split long text so each MTL call stays under the internal ~1000 speech-token cap."""
    raw = (text or "").strip()
    if not raw:
        return []
    try:
        lim = int(os.environ.get("PERKYSUE_MTL_CHUNK_CHARS", "").strip() or max_chars)
        lim = max(120, min(lim, 1200))
    except ValueError:
        lim = max_chars
    if len(raw) <= lim:
        return [raw]

    chunks: List[str] = []
    for para in re.split(r"\n\s*\n", raw):
        p = para.strip()
        if not p:
            continue
        if len(p) <= lim:
            chunks.append(p)
            continue
        buf = ""
        parts = re.split(r"(?<=[.!?…])\s+", p)
        for sent in parts:
            s = (sent or "").strip()
            if not s:
                continue
            if len(s) > lim:
                if buf:
                    chunks.append(buf.strip())
                    buf = ""
                for i in range(0, len(s), lim):
                    chunks.append(s[i : i + lim].strip())
                continue
            cand = f"{buf} {s}".strip() if buf else s
            if len(cand) <= lim:
                buf = cand
            else:
                if buf:
                    chunks.append(buf.strip())
                buf = s
        if buf:
            chunks.append(buf.strip())
    return [c for c in chunks if c.strip()]


_PATCH_CHATTERBOX_HUB = "_perkysue_chatterbox_hub_cache_patched"
_PATCH_CHATTERBOX_MTL_HUB = "_perkysue_chatterbox_mtl_hub_cache_patched"


def normalize_speech_lang(code: Optional[str]) -> str:
    """Map STT / config language hints to a 2-letter code for TTS (default English)."""
    if not code:
        return "en"
    c = str(code).strip().lower().replace("_", "-")
    if "-" in c:
        c = c.split("-")[0]
    aliases = {
        "english": "en",
        "french": "fr",
        "spanish": "es",
        "german": "de",
        "italian": "it",
        "portuguese": "pt",
        "dutch": "nl",
        "russian": "ru",
        "chinese": "zh",
        "japanese": "ja",
        "korean": "ko",
        "arabic": "ar",
        "hindi": "hi",
        "polish": "pl",
        "turkish": "tr",
        "swedish": "sv",
        "norwegian": "no",
        "finnish": "fi",
        "danish": "da",
        "greek": "el",
        "hebrew": "he",
        "malay": "ms",
        "swahili": "sw",
    }
    if c in aliases:
        c = aliases[c]
    return c if len(c) == 2 else "en"


def is_chatterbox_speech_supported(lang: str) -> bool:
    """True if Chatterbox can speak this language (Turbo English or multilingual model)."""
    lc = normalize_speech_lang(lang)
    if lc == "en":
        return True
    try:
        from chatterbox.mtl_tts import SUPPORTED_LANGUAGES
    except Exception:
        return lc == "en"
    return lc in SUPPORTED_LANGUAGES


# ISO 639-1 codes not in Chatterbox MTL — friendly English names for notifications
_SPEECH_LANG_EXTRA_EN = {
    "bn": "Bengali",
    "fa": "Persian",
    "uk": "Ukrainian",
    "vi": "Vietnamese",
    "th": "Thai",
    "ta": "Tamil",
    "te": "Telugu",
    "ur": "Urdu",
    "cs": "Czech",
    "ro": "Romanian",
    "hu": "Hungarian",
    "id": "Indonesian",
}


def speech_language_display_name_en(lang: str) -> str:
    """English display name for header notification (e.g. French, Bengali)."""
    lc = normalize_speech_lang(lang)
    if lc in _SPEECH_LANG_EXTRA_EN:
        return _SPEECH_LANG_EXTRA_EN[lc]
    try:
        from chatterbox.mtl_tts import SUPPORTED_LANGUAGES

        name = SUPPORTED_LANGUAGES.get(lc)
        if name:
            return name
    except Exception:
        pass
    return lc.upper()


def patch_chatterbox_mtl_hub_cache(hf_home: Path) -> None:
    """Same as Turbo: force ``snapshot_download`` for multilingual weights into portable ``Data/HuggingFace/hub``."""
    hf_home = hf_home.resolve()
    hub = str(hf_home / "hub")
    (hf_home / "hub").mkdir(parents=True, exist_ok=True)
    # Windows: avoid symlink/hardlink privilege issues when HF Hub populates snapshots.
    # This prevents WinError 1314 on machines without Developer Mode / symlink privilege.
    if os.name == "nt":
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")

    import torch
    import chatterbox.mtl_tts as mtl_mod
    from huggingface_hub import snapshot_download

    if getattr(mtl_mod, _PATCH_CHATTERBOX_MTL_HUB, False):
        return

    @classmethod
    def _from_pretrained_portable(cls, device):
        if device == "mps" and not torch.backends.mps.is_available():
            if not torch.backends.mps.is_built():
                print(
                    "MPS not available because the current PyTorch install was not built with MPS enabled."
                )
            else:
                print(
                    "MPS not available because the current MacOS version is not 12.3+ and/or "
                    "you do not have an MPS-enabled device on this machine."
                )
            device = "cpu"

        ckpt_dir = Path(
            snapshot_download(
                repo_id=mtl_mod.REPO_ID,
                repo_type="model",
                revision="main",
                allow_patterns=[
                    "ve.pt",
                    "t3_mtl23ls_v2.safetensors",
                    "s3gen.pt",
                    "grapheme_mtl_merged_expanded_v1.json",
                    "conds.pt",
                    "Cangjie5_TC.json",
                ],
                token=os.getenv("HF_TOKEN") or None,
                cache_dir=hub,
            )
        )
        return cls.from_local(ckpt_dir, device)

    mtl_mod.ChatterboxMultilingualTTS.from_pretrained = _from_pretrained_portable
    setattr(mtl_mod, _PATCH_CHATTERBOX_MTL_HUB, True)
    logger.info("Chatterbox MTL: using portable Hub cache at %s", hub)


def patch_chatterbox_turbo_hub_cache(hf_home: Path) -> None:
    """Bind Chatterbox ``from_pretrained`` to ``snapshot_download(..., cache_dir=Data/HuggingFace/hub)``.

    Without this, ``huggingface_hub`` may have resolved ``HF_HUB_CACHE`` to the user profile at
    import time (before ``paths.set_env()``), so weights would land under ``~/.cache/...``.
    """
    hf_home = hf_home.resolve()
    hub = str(hf_home / "hub")
    (hf_home / "hub").mkdir(parents=True, exist_ok=True)
    # Windows: avoid symlink/hardlink privilege issues when HF Hub populates snapshots.
    if os.name == "nt":
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")

    import torch
    import chatterbox.tts_turbo as tt_mod
    from huggingface_hub import snapshot_download

    if getattr(tt_mod, _PATCH_CHATTERBOX_HUB, False):
        return

    @classmethod
    def _from_pretrained_portable(cls, device: str):
        if device == "mps" and not torch.backends.mps.is_available():
            if not torch.backends.mps.is_built():
                print(
                    "MPS not available because the current PyTorch install was not built with MPS enabled."
                )
            else:
                print(
                    "MPS not available because the current MacOS version is not 12.3+ and/or "
                    "you do not have an MPS-enabled device on this machine."
                )
            device = "cpu"

        local_path = snapshot_download(
            repo_id=tt_mod.REPO_ID,
            token=os.getenv("HF_TOKEN") or None,
            allow_patterns=["*.safetensors", "*.json", "*.txt", "*.pt", "*.model"],
            cache_dir=hub,
        )
        return cls.from_local(local_path, device)

    tt_mod.ChatterboxTurboTTS.from_pretrained = _from_pretrained_portable
    setattr(tt_mod, _PATCH_CHATTERBOX_HUB, True)
    logger.info("Chatterbox: using portable Hub cache at %s", hub)


def ensure_perth_watermarker_fallback() -> None:
    """Chatterbox calls ``perth.PerthImplicitWatermarker()`` in ``__init__``. The ``perth`` package
    sets that name to ``None`` when its neural stack fails to import (common on minimal Windows
    installs). Patch in a no-op watermarker so the engine can load."""
    import perth

    if getattr(perth, "PerthImplicitWatermarker", None) is None:
        logger.warning(
            "PerthImplicitWatermarker unavailable — using DummyWatermarker (audio works; no neural watermark)."
        )
        perth.PerthImplicitWatermarker = perth.DummyWatermarker


# Engine metadata (used by TTSManager and GUI)
ENGINE_ID = "chatterbox"
ENGINE_META = {
    "id": ENGINE_ID,
    "name": "Chatterbox Turbo",
    "version": "1.0.0",
    "author": "Resemble AI",
    "license": "MIT",
    "description": (
        "English (Turbo) is fast. Non-English uses a separate multilingual model — often very slow on CPU; "
        "not recommended for daily non-English use. Prefer OmniVoice for multilingual replies."
    ),
    "multilingual_not_recommended": True,
    "pip_package": "chatterbox-tts",
    "model_size_mb": 1024,
    "parameters": "350M",
    "min_vram_mb": 4500,
    "cpu_fallback": True,
    "languages": ["en"],
    "cloning": True,
    "streaming": True,
}


def is_pip_installed() -> bool:
    """Check if chatterbox-tts pip package is importable."""
    try:
        import chatterbox  # noqa: F401
        return True
    except ImportError:
        return False


def is_model_downloaded(models_dir: Path) -> bool:
    """Return True if the pip package is present.

    Chatterbox weights are stored by Hugging Face Hub under ``Data/HuggingFace/hub/`` (see
    ``paths.huggingface``), not under ``Data/Models/TTS/`` — that folder is for other engines
    or future layouts.
    """
    return is_pip_installed()


class ChatterboxTTS(TTSEngine):
    """Chatterbox Turbo (English) + lazy multilingual model for other ISO codes in ``mtl_tts.SUPPORTED_LANGUAGES``."""

    def __init__(self, models_dir: Path, cache_dir: Optional[Path] = None):
        self.models_dir = models_dir
        self.cache_dir = cache_dir
        self._model = None
        self._model_mtl = None
        self._device = "cpu"
        self._sample_rate = 24000
        self._warmup_error: Optional[str] = None
        self._diagnostics_paths: Optional[Any] = None
        # Filled after ``import torch`` in warmup: False = CPU-only wheel (no CUDA in PyTorch).
        self._pytorch_cuda_built: Optional[bool] = None
        self._pytorch_version: str = ""

    def warmup(self, paths: Optional[Any] = None):
        """Load model into GPU/CPU/MPS memory.

        ``paths`` (optional ``Paths``) enables dev-plugin diagnostics when ``Data/Plugins/dev/manifest.yaml`` exists.
        """
        self._warmup_error = None
        self._diagnostics_paths = paths
        clear_blank_cuda_visible_devices()
        log_tts_dev_device_diagnostics(paths, "after_clear_blank", "chatterbox")
        if not is_pip_installed():
            logger.warning("chatterbox-tts not installed — run install from Voice tab")
            return

        try:
            ensure_perth_watermarker_fallback()
            import torch

            try:
                self._pytorch_cuda_built = bool(torch.backends.cuda.is_built())
                self._pytorch_version = str(torch.__version__)
            except Exception:
                self._pytorch_cuda_built = None
                self._pytorch_version = ""
            if self._pytorch_cuda_built is False:
                logger.warning(
                    "Chatterbox: PyTorch has no CUDA support (%s). TTS will stay on CPU until you "
                    "install a CUDA PyTorch wheel in this Python (see Voice tab warning or "
                    "install_pytorch_cuda_cu124.bat).",
                    self._pytorch_version or "?",
                )
            log_tts_dev_device_diagnostics(paths, "after_torch_import", "chatterbox")
            if self.cache_dir:
                root = str(self.cache_dir.resolve())
                os.environ["HF_HOME"] = root
                os.environ["HF_HUB_CACHE"] = str(self.cache_dir.resolve() / "hub")
                os.environ["HUGGINGFACE_HUB_CACHE"] = os.environ["HF_HUB_CACHE"]
                patch_chatterbox_turbo_hub_cache(self.cache_dir)
            from chatterbox.tts_turbo import ChatterboxTurboTTS

            device = _resolve_chatterbox_torch_device(torch)
            self._device = device
            if (os.environ.get("PERKYSUE_CHATTERBOX_DEVICE") or "").strip():
                logger.info("Chatterbox Turbo: device forced by PERKYSUE_CHATTERBOX_DEVICE=%s → %s", os.environ.get("PERKYSUE_CHATTERBOX_DEVICE"), device)
            log_tts_dev_device_diagnostics(paths, "before_turbo_from_pretrained", "chatterbox", chosen_device=device)

            logger.info("Chatterbox Turbo: loading on %s...", device)
            t0 = time.monotonic()
            self._model = ChatterboxTurboTTS.from_pretrained(device=device)
            self._sample_rate = self._model.sr

            # PyTorch may report CUDA available on very new GPUs while kernels/synthesis return silence.
            # Probe once; fall back to CPU so TTS keeps working (e.g. RTX 5090 + cu124 wheel quirks).
            probe = None
            if device != "cpu":
                try:
                    with torch.inference_mode():
                        probe = self._model.generate("Hi.")
                except Exception as ex:
                    logger.warning("Chatterbox Turbo: probe generate on %s failed: %s", device, ex)
                    probe = None
                if not _turbo_wav_sane(probe):
                    logger.warning(
                        "Chatterbox Turbo: probe output invalid on %s — reloading on CPU "
                        "(GPU/driver stack may not fully support this model yet; "
                        "set PERKYSUE_CHATTERBOX_DEVICE=cpu to always skip GPU).",
                        device,
                    )
                    try:
                        del self._model
                    except Exception:
                        pass
                    self._model = None
                    try:
                        del probe
                    except Exception:
                        pass
                    probe = None
                    try:
                        torch.cuda.empty_cache()
                    except Exception:
                        pass
                    device = "cpu"
                    self._device = device
                    log_tts_dev_device_diagnostics(paths, "turbo_reload_cpu_after_bad_probe", "chatterbox", chosen_device=device)
                    self._model = ChatterboxTurboTTS.from_pretrained(device=device)
                    self._sample_rate = self._model.sr
                    with torch.inference_mode():
                        probe = self._model.generate("Hi.")
                    if not _turbo_wav_sane(probe):
                        raise RuntimeError("Chatterbox Turbo: CPU probe generation also invalid")
                try:
                    del probe
                except Exception:
                    pass
                probe = None

            logger.info("Chatterbox Turbo: ready on %s (%.1fs)", device, time.monotonic() - t0)
            log_tts_dev_device_diagnostics(paths, "after_turbo_ready", "chatterbox", chosen_device=device)

        except Exception as e:
            self._warmup_error = str(e)
            logger.error("Chatterbox warmup failed: %s", e)
            self._model = None
            log_tts_dev_device_diagnostics(paths, "warmup_failed", "chatterbox")

    def _ensure_mtl_model(self):
        if self._model_mtl is not None:
            return
        clear_blank_cuda_visible_devices()
        log_tts_dev_device_diagnostics(
            getattr(self, "_diagnostics_paths", None),
            "mtl_after_clear",
            "chatterbox-mtl",
            chosen_device=self._device,
        )
        ensure_perth_watermarker_fallback()
        if self.cache_dir:
            root = str(self.cache_dir.resolve())
            os.environ["HF_HOME"] = root
            os.environ["HF_HUB_CACHE"] = str(self.cache_dir.resolve() / "hub")
            os.environ["HUGGINGFACE_HUB_CACHE"] = os.environ["HF_HUB_CACHE"]
            patch_chatterbox_mtl_hub_cache(self.cache_dir)
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS

        logger.info("Chatterbox: loading multilingual model for non-English speech (one-time)...")
        t0 = time.monotonic()
        self._model_mtl = ChatterboxMultilingualTTS.from_pretrained(device=self._device)
        logger.info("Chatterbox multilingual: ready (%.1fs)", time.monotonic() - t0)
        log_tts_dev_device_diagnostics(
            getattr(self, "_diagnostics_paths", None),
            "after_mtl_ready",
            "chatterbox-mtl",
            chosen_device=self._device,
        )

    def synthesize(
        self,
        text: str,
        voice: Optional[VoiceInfo] = None,
        language: Optional[str] = None,
        speed: float = 1.0,
        mtl_chunk_audio_callback: Optional[Callable] = None,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> TTSResult:
        if not self.is_available():
            raise RuntimeError("Chatterbox not available")

        import numpy as np
        t0 = time.monotonic()
        lang = normalize_speech_lang(language or "en")
        already_streamed_out = False

        gen_kwargs = {}
        if voice and voice.ref_audio:
            ref = Path(voice.ref_audio)
            if ref.exists():
                gen_kwargs["audio_prompt_path"] = str(ref)
            else:
                logger.warning("Voice ref audio not found: %s", ref)

        if lang == "en":
            wav = self._model.generate(text, **gen_kwargs)
            engine_tag = "chatterbox-turbo"
        else:
            self._ensure_mtl_model()
            assert self._model_mtl is not None
            chunks = _mtl_chunk_text(text)
            if not chunks:
                raise RuntimeError("Chatterbox MTL: empty text")
            sr_mtl = int(self._model_mtl.sr)
            try:
                gap_s = float((os.environ.get("PERKYSUE_MTL_CHUNK_GAP_S") or "0.12").strip() or 0.12)
            except ValueError:
                gap_s = 0.12
            gap_s = max(0.0, min(gap_s, 1.0))
            gap_n = int(sr_mtl * gap_s)
            gap = np.zeros(max(0, gap_n), dtype=np.float32)

            piece_list: List[np.ndarray] = []
            stream_play = bool(mtl_chunk_audio_callback) and len(chunks) > 1
            already_streamed_out = stream_play

            # Best-effort cancellation *during* sampling (not only between chunks).
            # The upstream library may (or may not) support callbacks/stop_event; detect safely.
            try:
                sig = inspect.signature(self._model_mtl.generate)
                gen_param_names = set(sig.parameters.keys())
            except Exception:
                gen_param_names = set()

            class _StopProxy:
                def is_set(self) -> bool:
                    try:
                        return bool(should_stop and should_stop())
                    except Exception:
                        return False

            def _cancel_callback(*_a, **_k):
                if should_stop and should_stop():
                    raise RuntimeError("Chatterbox MTL: cancelled")

            for i, ch in enumerate(chunks):
                if should_stop and should_stop():
                    raise RuntimeError("Chatterbox MTL: cancelled")
                kw = dict(gen_kwargs)
                if i > 0 and "audio_prompt_path" in kw:
                    del kw["audio_prompt_path"]
                if len(chunks) > 1:
                    logger.info("Chatterbox MTL: chunk %d/%d (%d chars)", i + 1, len(chunks), len(ch))
                # Inject cancellation hooks if supported by this chatterbox version.
                try:
                    if should_stop and gen_param_names:
                        if "stop_event" in gen_param_names and "stop_event" not in kw:
                            kw["stop_event"] = _StopProxy()
                        for cb_name in ("callback", "progress_callback", "step_callback", "on_step", "on_progress"):
                            if cb_name in gen_param_names and cb_name not in kw:
                                kw[cb_name] = _cancel_callback
                                break
                except Exception:
                    pass

                wav = self._model_mtl.generate(ch, language_id=lang, **kw)
                if should_stop and should_stop():
                    raise RuntimeError("Chatterbox MTL: cancelled")
                if hasattr(wav, "cpu"):
                    arr = wav.cpu().numpy().squeeze().astype(np.float32)
                else:
                    arr = np.array(wav).squeeze().astype(np.float32)
                if stream_play and mtl_chunk_audio_callback:
                    if piece_list and gap.size:
                        mtl_chunk_audio_callback(gap, sr_mtl)
                    mtl_chunk_audio_callback(arr, sr_mtl)
                if piece_list and gap.size:
                    piece_list.append(gap)
                piece_list.append(arr)
            audio = np.concatenate(piece_list) if len(piece_list) > 1 else piece_list[0]
            engine_tag = "chatterbox-mtl"

        # To numpy float32 (English path still returns tensor from Turbo)
        if lang == "en":
            if hasattr(wav, "cpu"):
                audio = wav.cpu().numpy().squeeze()
            else:
                audio = np.array(wav).squeeze()
            audio = audio.astype(np.float32)
        if audio.size == 0:
            raise RuntimeError("Chatterbox: empty audio buffer")
        peak = float(np.abs(audio).max())
        if peak < 1e-8:
            raise RuntimeError(
                "Chatterbox: silent audio output. If you use CUDA PyTorch, try PERKYSUE_CHATTERBOX_DEVICE=cpu "
                "or restart PerkySue so the engine can fall back to CPU."
            )
        if peak > 1.0:
            audio = audio / peak

        sr = self._sample_rate
        if lang != "en" and self._model_mtl is not None:
            sr = int(self._model_mtl.sr)

        duration = len(audio) / sr
        elapsed = time.monotonic() - t0

        return TTSResult(
            audio=audio,
            sample_rate=sr,
            duration=duration,
            engine=engine_tag,
            rtf=elapsed / duration if duration > 0 else 0,
            already_streamed=already_streamed_out,
        )

    def is_available(self) -> bool:
        return self._model is not None

    def will_download_or_load_multilingual(self, lang: str) -> bool:
        """True if the next non-English synthesis will trigger MTL download/load (blocks a long time)."""
        return normalize_speech_lang(lang) != "en" and self._model_mtl is None

    def get_name(self) -> str:
        return "Chatterbox Turbo"

    def get_voices(self) -> List[VoiceInfo]:
        return [VoiceInfo(id="default", name="Pro (default)", gender="neutral", source="builtin")]

    def get_languages(self) -> List[str]:
        try:
            from chatterbox.mtl_tts import SUPPORTED_LANGUAGES

            return sorted(set(["en"]) | set(SUPPORTED_LANGUAGES.keys()))
        except Exception:
            return ["en"]

    def supports_cloning(self) -> bool:
        return True

    def supports_streaming(self) -> bool:
        return True

    def get_vram_estimate_mb(self) -> Optional[int]:
        return 4500

    def unload(self):
        if self._model_mtl is not None:
            logger.info("Chatterbox: unloading multilingual model")
            del self._model_mtl
            self._model_mtl = None
        if self._model is not None:
            logger.info("Chatterbox: unloading model")
            del self._model
            self._model = None
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass
