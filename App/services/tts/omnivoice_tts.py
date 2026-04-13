"""
OmniVoice TTS engine (k2-fsa) — multilingual, fast inference vs Chatterbox MTL on CPU.

Optional dependency: ``pip install omnivoice``. This module must not import torch at top level.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .base import TTSEngine, TTSResult, VoiceInfo
from .chatterbox_tts import (
    clear_blank_cuda_visible_devices,
    log_tts_dev_device_diagnostics,
    normalize_speech_lang,
)
from .pytorch_cuda import torch_gpu_runs_basic_kernels
from .windows_ffmpeg_dlls import register_portable_ffmpeg_dll_directories

logger = logging.getLogger("perkysue.tts.omnivoice")

# TorchAudio 2.9+ uses TorchCodec for load/save (FFmpeg DLLs on Windows). We route local .wav via soundfile.
_LOCAL_WAV_TORCHAUDIO_PATCH: bool = False

def local_wav_torchaudio_patch_active() -> bool:
    return _LOCAL_WAV_TORCHAUDIO_PATCH


def _apply_local_wav_torchaudio_patch() -> None:
    global _LOCAL_WAV_TORCHAUDIO_PATCH
    import os

    import torchaudio

    if getattr(torchaudio, "_perkysue_wav_patch", False):
        _LOCAL_WAV_TORCHAUDIO_PATCH = True
        return
    try:
        import soundfile as sf  # noqa: F401
    except ImportError:
        logger.warning(
            "OmniVoice: soundfile missing — reference audio may require torchcodec and FFmpeg on PATH"
        )
        return

    _orig_load = torchaudio.load

    def load(
        uri,
        frame_offset=0,
        num_frames=-1,
        normalize=True,
        channels_first=True,
        format=None,
        buffer_size=4096,
        backend=None,
    ):
        path_str = None
        if isinstance(uri, (str, os.PathLike)):
            ps = os.fspath(uri)
            if os.path.isfile(ps) and ps.lower().endswith((".wav", ".wave")):
                path_str = ps
        if path_str is not None:
            try:
                import numpy as np
                import soundfile as sf
                import torch

                data, sr = sf.read(path_str, dtype="float32", always_2d=True)
                if frame_offset > 0:
                    if frame_offset >= len(data):
                        ch = int(data.shape[1]) if data.ndim > 1 else 1
                        data = np.zeros((0, ch), dtype=np.float32)
                    else:
                        data = data[frame_offset:]
                if num_frames is not None and num_frames >= 0:
                    data = data[:num_frames]
                t = torch.from_numpy(np.ascontiguousarray(data))
                if channels_first:
                    t = t.t().contiguous() if t.ndim == 2 else t.unsqueeze(0)
                else:
                    if t.ndim == 2:
                        t = t.contiguous()
                    else:
                        t = t.unsqueeze(-1)
                return t, int(sr)
            except Exception as e:
                logger.debug("OmniVoice: soundfile WAV load failed, using torchaudio: %s", e)

        return _orig_load(
            uri,
            frame_offset=frame_offset,
            num_frames=num_frames,
            normalize=normalize,
            channels_first=channels_first,
            format=format,
            buffer_size=buffer_size,
            backend=backend,
        )

    _orig_save = torchaudio.save

    def save(
        uri,
        src,
        sample_rate,
        channels_first=True,
        format=None,
        encoding=None,
        bits_per_sample=None,
        buffer_size=4096,
        backend=None,
        compression=None,
    ):
        if isinstance(uri, (str, os.PathLike)):
            path = os.fspath(uri)
            if path.lower().endswith((".wav", ".wave")):
                try:
                    import numpy as np
                    import soundfile as sf

                    x = src.detach().cpu().float()
                    if x.dim() == 1:
                        arr = x.unsqueeze(1).numpy()
                    elif channels_first:
                        arr = x.transpose(0, 1).contiguous().numpy()
                    else:
                        arr = x.numpy()
                    subtype = "FLOAT"
                    if bits_per_sample == 16:
                        subtype = "PCM_16"
                    elif bits_per_sample == 24:
                        subtype = "PCM_24"
                    elif bits_per_sample == 32:
                        subtype = "PCM_32"
                    sf.write(path, arr, int(sample_rate), subtype=subtype)
                    return
                except Exception as e:
                    logger.debug("OmniVoice: soundfile WAV save failed: %s", e)

        return _orig_save(
            uri,
            src,
            sample_rate,
            channels_first=channels_first,
            format=format,
            encoding=encoding,
            bits_per_sample=bits_per_sample,
            buffer_size=buffer_size,
            backend=backend,
            compression=compression,
        )

    torchaudio.load = load
    torchaudio.save = save
    torchaudio._perkysue_wav_patch = True
    _LOCAL_WAV_TORCHAUDIO_PATCH = True
    logger.info(
        "OmniVoice: torchaudio.load/save patched for local .wav via soundfile (TorchCodec/FFmpeg optional for WAV)"
    )


ENGINE_ID = "omnivoice"
ENGINE_META = {
    "id": ENGINE_ID,
    "name": "OmniVoice",
    "version": "0.1.x",
    "author": "k2-fsa",
    "license": "Apache-2.0",
    "description": (
        "Multilingual zero-shot TTS (600+ languages). Recommended when your replies are not English — "
        "typically much faster than Chatterbox’s multilingual path on CPU."
    ),
    "pip_package": "omnivoice",
    "model_size_mb": 2048,
    "parameters": "—",
    "min_vram_mb": 4000,
    "cpu_fallback": True,
    "languages": ["*"],
    "cloning": True,
    "streaming": False,
}


def is_pip_installed() -> bool:
    try:
        import omnivoice  # noqa: F401
        return True
    except ImportError:
        return False


def _apply_hf_cache(cache_dir: Optional[Path]) -> None:
    if not cache_dir:
        return
    root = str(cache_dir.resolve())
    os.environ["HF_HOME"] = root
    hub = str((cache_dir / "hub").resolve())
    os.environ["HF_HUB_CACHE"] = hub
    os.environ["HUGGINGFACE_HUB_CACHE"] = hub


class OmniVoiceTTS(TTSEngine):
    """OmniVoice wrapper; options come from a callback (TTSManager fields)."""

    def __init__(
        self,
        models_dir: Path,
        cache_dir: Optional[Path],
        get_options: Callable[[], Dict],
        model_local_dir: Optional[Path] = None,
        allow_online_fetch: bool = True,
    ):
        self.models_dir = models_dir
        self.cache_dir = cache_dir
        self._get_options = get_options
        self.model_local_dir = Path(model_local_dir) if model_local_dir else None
        self.allow_online_fetch = bool(allow_online_fetch)
        self._model = None
        self._device = "cpu"
        self._sample_rate = 24000
        self._warmup_error: Optional[str] = None
        self._diagnostics_paths: Optional[Any] = None
        self._pytorch_cuda_built: Optional[bool] = None
        self._pytorch_version: str = ""

    def warmup(self, paths: Optional[Any] = None) -> None:
        self._warmup_error = None
        self._diagnostics_paths = paths
        clear_blank_cuda_visible_devices()
        log_tts_dev_device_diagnostics(paths, "after_clear_blank", "omnivoice")
        if not is_pip_installed():
            logger.warning("omnivoice not installed — use Voice tab → Install")
            return

        opts = self._get_options() if self._get_options else {}
        repo = (opts.get("omnivoice_repo") or "k2-fsa/OmniVoice").strip() or "k2-fsa/OmniVoice"

        try:
            register_portable_ffmpeg_dll_directories(paths)
            _apply_hf_cache(self.cache_dir)
            import torch
            import torchaudio

            _apply_local_wav_torchaudio_patch()

            try:
                self._pytorch_cuda_built = bool(torch.backends.cuda.is_built())
                self._pytorch_version = str(torch.__version__)
            except Exception:
                self._pytorch_cuda_built = None
                self._pytorch_version = ""
            if self._pytorch_cuda_built is False:
                logger.warning(
                    "OmniVoice: PyTorch has no CUDA support (%s). TTS will stay on CPU until you install "
                    "a CUDA PyTorch wheel (see Voice tab or install_pytorch_cuda_cu124.bat).",
                    self._pytorch_version or "?",
                )
            log_tts_dev_device_diagnostics(paths, "after_torch_import", "omnivoice")
            from omnivoice import OmniVoice

            if torch.cuda.is_available() and torch_gpu_runs_basic_kernels():
                device_map = "cuda:0"
                torch_dtype = torch.float16
                self._device = "cuda"
            elif torch.cuda.is_available():
                logger.warning(
                    "OmniVoice: CUDA visible but kernel probe failed (unsupported GPU vs PyTorch build). Using CPU."
                )
                device_map = "cpu"
                torch_dtype = torch.float32
                self._device = "cpu"
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                device_map = "mps"
                torch_dtype = torch.float32
                self._device = "mps"
            else:
                device_map = "cpu"
                torch_dtype = torch.float32
                self._device = "cpu"

            log_tts_dev_device_diagnostics(
                paths, "before_from_pretrained", "omnivoice", chosen_device=self._device
            )
            logger.info("OmniVoice: loading %s on %s...", repo, self._device)
            t0 = time.monotonic()
            load_ref = repo
            if self.model_local_dir and self.model_local_dir.is_dir():
                load_ref = str(self.model_local_dir)
            elif not self.allow_online_fetch:
                raise RuntimeError(
                    "OmniVoice model manifest is missing/invalid. Use Voice tab Repair/Install."
                )
            self._model = OmniVoice.from_pretrained(
                load_ref,
                torch_dtype=torch_dtype,
                device_map=device_map,
            )
            # Cache for voice cloning prompts (avoid re-encoding reference audio every call).
            # Key: (ref_audio_path, ref_text)
            self._voice_clone_prompt_cache = {}
            self._sample_rate = int(getattr(self._model, "sampling_rate", None) or 24000)
            logger.info("OmniVoice: ready (%.1fs)", time.monotonic() - t0)
            log_tts_dev_device_diagnostics(
                paths, "after_ready", "omnivoice", chosen_device=self._device
            )
        except Exception as e:
            self._warmup_error = str(e)
            logger.error("OmniVoice warmup failed: %s", e)
            self._model = None
            log_tts_dev_device_diagnostics(paths, "warmup_failed", "omnivoice")

    def synthesize(
        self,
        text: str,
        voice: Optional[VoiceInfo] = None,
        language: Optional[str] = None,
        speed: float = 1.0,
    ) -> TTSResult:
        if not self.is_available():
            raise RuntimeError("OmniVoice not available")

        register_portable_ffmpeg_dll_directories(self._diagnostics_paths)

        import numpy as np

        opts = self._get_options() if self._get_options else {}
        # Clone-only for now (design mode hidden until ready).
        mode = "clone"
        num_step = int(opts.get("omnivoice_num_step") or 32)
        num_step = max(8, min(num_step, 64))

        lang = normalize_speech_lang(language or "en")
        t0 = time.monotonic()

        gen_kw: Dict = {
            "text": text,
            "language": lang,
            "speed": float(speed) if speed else 1.0,
            "num_step": num_step,
        }
        # Follow OmniVoice demo defaults where possible (pre/postprocessing helps avoid prompt artifacts).
        try:
            from omnivoice import OmniVoiceGenerationConfig  # type: ignore

            gen_kw["generation_config"] = OmniVoiceGenerationConfig(
                num_step=int(num_step),
                guidance_scale=2.0,
                denoise=True,
                preprocess_prompt=True,
                postprocess_output=True,
            )
            # Do not pass the same parameters twice (generation_config already includes num_step etc.).
            gen_kw.pop("num_step", None)
        except Exception:
            pass

        ref_path = None
        if voice and voice.ref_audio:
            p = Path(voice.ref_audio)
            if p.is_file():
                ref_path = str(p)

        if mode == "clone":
            if ref_path:
                # Prefer `create_voice_clone_prompt()` so ref_text isn't passed to `generate()`.
                # Passing ref_text to `generate()` can leak into spoken output (sample phrase replay).
                # ref_text is important for alignment: without it, OmniVoice can skip words/sentences.
                # We still avoid passing it to `generate()` by using `voice_clone_prompt`.
                rt = ""
                if voice and getattr(voice, "ref_transcript", None):
                    rt = (voice.ref_transcript or "").strip()
                try:
                    cache = getattr(self, "_voice_clone_prompt_cache", None)
                    key = (ref_path, rt)
                    if isinstance(cache, dict) and key in cache:
                        vcp = cache[key]
                    else:
                        vcp = self._model.create_voice_clone_prompt(ref_audio=ref_path, ref_text=rt or "")
                        if isinstance(cache, dict):
                            cache[key] = vcp
                    gen_kw["voice_clone_prompt"] = vcp
                except Exception as e:
                    logger.warning("OmniVoice: create_voice_clone_prompt failed (%s) — falling back to ref_audio", e)
                    gen_kw["ref_audio"] = ref_path
                    # Avoid Whisper ASR download, and avoid any prefixing side-effects.
                    gen_kw["ref_text"] = (rt or "").strip()
            else:
                logger.warning("OmniVoice clone mode: no reference audio — falling back to auto voice")
        # else: auto voice (no instruct, no ref_audio)

        audios = self._model.generate(**gen_kw)
        if not audios:
            raise RuntimeError("OmniVoice returned no audio")
        wav = audios[0]
        if hasattr(wav, "cpu"):
            audio = wav.detach().cpu().float().numpy().squeeze()
        else:
            audio = np.array(wav).squeeze()
        audio = audio.astype(np.float32)
        peak = float(np.abs(audio).max()) if audio.size else 0.0
        if peak > 1.0:
            audio = audio / peak

        sr = self._sample_rate
        duration = float(len(audio) / sr) if sr else 0.0
        elapsed = time.monotonic() - t0

        return TTSResult(
            audio=audio,
            sample_rate=sr,
            duration=duration,
            engine="omnivoice",
            rtf=elapsed / duration if duration > 0 else 0.0,
        )

    def is_available(self) -> bool:
        return self._model is not None

    def get_name(self) -> str:
        return "OmniVoice"

    def get_voices(self) -> List[VoiceInfo]:
        return [VoiceInfo(id="default", name="Auto / skin ref", gender="neutral", source="builtin")]

    def supports_cloning(self) -> bool:
        return True

    def get_vram_estimate_mb(self) -> Optional[int]:
        return 6000

    def unload(self) -> None:
        if self._model is not None:
            logger.info("OmniVoice: unloading model")
            del self._model
            self._model = None
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass
