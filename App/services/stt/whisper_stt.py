"""
Provider STT utilisant faster-whisper (CTranslate2).
Version portable: télécharge les modèles dans Data/Models/Whisper/
"""

import logging
import os
import subprocess
import shutil
from typing import List, Optional, Tuple
import numpy as np

from .base import STTProvider, TranscriptionResult

logger = logging.getLogger("perkysue.stt.whisper")

# VRAM minimum (MB) pour utiliser le GPU en mode Auto (Whisper medium ~2 GB)
STT_CUDA_MIN_VRAM_MB = 2048


def _get_nvidia_free_vram_mb() -> Optional[float]:
    """Retourne la VRAM libre en Mo (premier GPU) ou None si indisponible."""
    if not shutil.which("nvidia-smi"):
        return None
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
        if out.returncode != 0 or not out.stdout.strip():
            return None
        return float(out.stdout.strip().split("\n")[0].strip().split()[0])
    except Exception:
        return None


def _merge_transcript_chunks(parts: List[str]) -> str:
    """Join chunk transcripts; drop duplicated words at chunk boundaries (overlap audio)."""
    out = (parts[0] or "").strip() if parts else ""
    for nxt in parts[1:]:
        nxt = (nxt or "").strip()
        if not nxt:
            continue
        if not out:
            out = nxt
            continue
        a = out.split()
        b = nxt.split()
        if not a or not b:
            out = f"{out} {nxt}".strip()
            continue
        max_k = min(len(a), len(b))
        best = 0
        for k in range(1, max_k + 1):
            if a[-k:] == b[:k]:
                best = k
        if best:
            out = " ".join(a + b[best:])
        else:
            out = f"{out} {nxt}".strip()
    return out


class WhisperSTT(STTProvider):

    def __init__(self, model_size: str = "medium", device: str = "auto",
                 compute_type: str = "auto", models_dir: str = None,
                 cache_dir: str = None, initial_prompt: str = None,
                 chunk_length_sec: float = 0.0,
                 chunk_overlap_sec: float = 1.0,
                 chunk_min_audio_sec: float = 45.0):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.models_dir = models_dir    # Data/Models/Whisper
        self.cache_dir = cache_dir      # Data/HuggingFace
        self.initial_prompt = (initial_prompt or "").strip() or None  # e.g. "PerkySue" to fix recognition
        self.chunk_length_sec = float(chunk_length_sec or 0.0)
        self.chunk_overlap_sec = max(0.0, float(chunk_overlap_sec or 0.0))
        self.chunk_min_audio_sec = max(0.0, float(chunk_min_audio_sec or 0.0))
        self._model = None

    def set_initial_prompt(self, value: str):
        """Update initial_prompt at runtime (e.g. after user adds Whisper keywords in GUI)."""
        self.initial_prompt = (value or "").strip() or None

        # Force le cache HuggingFace dans notre dossier portable
        if self.cache_dir:
            os.environ["HF_HOME"] = self.cache_dir

    def _resolve_device(self) -> tuple[str, str]:
        device = self.device
        compute = self.compute_type

        if device == "auto":
            # CTranslate2 has its own CUDA support — no need for torch
            device = "cpu"
            backend = os.environ.get("PERKYSUE_BACKEND", "")
            cuda_available = False
            try:
                import ctranslate2
                # liste non vide = CUDA dispo (ex. ["float16","int8"])
                if ctranslate2.get_supported_compute_types("cuda"):
                    cuda_available = True
            except Exception:
                try:
                    import torch
                    if torch.cuda.is_available():
                        cuda_available = True
                except ImportError:
                    pass
            if cuda_available and backend.startswith("nvidia-"):
                free_mb = _get_nvidia_free_vram_mb()
                if free_mb is not None and free_mb < STT_CUDA_MIN_VRAM_MB:
                    logger.info(f"Auto: VRAM libre {free_mb:.0f} MB < {STT_CUDA_MIN_VRAM_MB} MB — Whisper en CPU pour éviter OOM")
                    device = "cpu"
                else:
                    device = "cuda"

        if compute == "auto":
            if device == "cuda":
                # float16 is fastest on GPU
                compute = "float16"
            else:
                # int8 is fastest on CPU
                compute = "int8"

        return device, compute

    def _load_model(self):
        if self._model is not None:
            return

        from faster_whisper import WhisperModel

        device, compute = self._resolve_device()
        logger.info(f"Loading Whisper '{self.model_size}' on {device} ({compute})...")

        # Si un dossier modèles portable est défini, on l'utilise
        download_root = self.models_dir if self.models_dir else None

        self._model = WhisperModel(
            self.model_size,
            device=device,
            compute_type=compute,
            download_root=download_root,
        )
        logger.info("Whisper model loaded.")
        backend = os.environ.get("PERKYSUE_BACKEND", "")
        if device == "cuda":
            print("   ✅ Whisper: GPU (CUDA) — transcription accélérée")
        elif backend == "vulkan":
            print("   Whisper: CPU (Vulkan GPU is used for LLM only — Whisper does not support Vulkan)")
        elif backend.startswith("nvidia-") and device == "cpu":
            if self.device == "cpu":
                print("   ⚠️ Whisper: CPU (config: stt.device is 'cpu' in Data/Configs/config.yaml — set to 'auto' for GPU)")
            else:
                print("   ⚠️ NVIDIA detected but ctranslate2 has no CUDA (CPU-only wheel). Re-run install.bat to install CUDA STT packages. If still CPU: pip uninstall ctranslate2 then run install.bat again.")
        else:
            print("   ⚠️ Whisper: CPU — pour GPU, installez faster-whisper avec support CUDA (pip install faster-whisper avec ctranslate2-cuda)")

    def _transcribe_options(self, language: Optional[str]) -> dict:
        options = {
            "beam_size": 5,
            "vad_filter": True,
            "vad_parameters": {"min_silence_duration_ms": 500},
        }
        if language and language != "auto":
            options["language"] = language
        if self.initial_prompt:
            options["initial_prompt"] = self.initial_prompt
        return options

    def _run_transcribe(
        self, audio_slice: np.ndarray, options: dict
    ) -> Tuple[str, object]:
        segments, info = self._model.transcribe(audio_slice, **options)
        text_parts = [segment.text.strip() for segment in segments]
        text = " ".join(text_parts).strip()
        return text, info

    def _transcribe_single_pass(
        self, audio_data: np.ndarray, sample_rate: int, language: Optional[str]
    ) -> TranscriptionResult:
        options = self._transcribe_options(language)
        text, info = self._run_transcribe(audio_data, options)
        lang = None
        if info is not None:
            lang = getattr(info, "language", None)
            if lang:
                lang = str(lang).strip().lower() or None
        if lang:
            logger.info(
                "Whisper detected / used language: %s (probability=%s)",
                lang,
                getattr(info, "language_probability", None),
            )
        duration_sec = len(audio_data) / float(sample_rate)
        return TranscriptionResult(
            text=text,
            language=lang,
            confidence=getattr(info, "language_probability", 0.0) if info else 0.0,
            duration=getattr(info, "duration", duration_sec) if info else duration_sec,
        )

    def _audio_chunk_indices(
        self, n_samples: int, sample_rate: int
    ) -> List[Tuple[int, int]]:
        if n_samples <= 0:
            return [(0, 0)]
        chunk = int(self.chunk_length_sec * sample_rate)
        overlap = int(self.chunk_overlap_sec * sample_rate)
        if chunk <= 0:
            return [(0, n_samples)]
        if n_samples <= chunk:
            return [(0, n_samples)]
        step = max(1, chunk - overlap)
        ranges: List[Tuple[int, int]] = []
        start = 0
        min_tail = max(sample_rate // 4, int(0.25 * sample_rate))  # ≥0.25s last slice
        while start < n_samples:
            end = min(start + chunk, n_samples)
            if end - start < min_tail and ranges:
                prev_s, _ = ranges[-1]
                ranges[-1] = (prev_s, n_samples)
                break
            ranges.append((start, end))
            if end >= n_samples:
                break
            start += step
        return ranges

    def _transcribe_chunked(
        self, audio_data: np.ndarray, sample_rate: int, language: Optional[str]
    ) -> TranscriptionResult:
        n = len(audio_data)
        duration_sec = n / float(sample_rate)
        ranges = [(s, e) for s, e in self._audio_chunk_indices(n, sample_rate) if e > s]
        if not ranges:
            return TranscriptionResult(
                text="",
                language=language if language and language != "auto" else None,
                confidence=0.0,
                duration=duration_sec,
            )
        logger.info(
            "Whisper long audio: %.1fs → %d chunk(s), len=%.1fs overlap=%.2fs",
            duration_sec,
            len(ranges),
            self.chunk_length_sec,
            self.chunk_overlap_sec,
        )
        texts: List[str] = []
        base_opts = self._transcribe_options(language)
        detected_lang = language if language and language != "auto" else None
        confidence = 0.0
        for i, (s, e) in enumerate(ranges):
            slice_ = audio_data[s:e]
            opts = dict(base_opts)
            if detected_lang:
                opts["language"] = detected_lang
            text, info = self._run_transcribe(slice_, opts)
            texts.append(text)
            if detected_lang is None and info is not None:
                raw = getattr(info, "language", None)
                if raw:
                    detected_lang = str(raw).strip().lower() or None
                    if detected_lang:
                        logger.info(
                            "Whisper chunk %d/%d: locked language %s (p=%s)",
                            i + 1,
                            len(ranges),
                            detected_lang,
                            getattr(info, "language_probability", None),
                        )
                confidence = max(
                    confidence, float(getattr(info, "language_probability", 0.0) or 0.0)
                )
        merged = _merge_transcript_chunks(texts)
        return TranscriptionResult(
            text=merged,
            language=detected_lang,
            confidence=confidence,
            duration=duration_sec,
        )

    def transcribe(self, audio_data: np.ndarray, sample_rate: int = 16000,
                   language: Optional[str] = None) -> TranscriptionResult:
        self._load_model()

        if audio_data.dtype != np.float32:
            audio_data = audio_data.astype(np.float32)

        duration_sec = len(audio_data) / float(sample_rate)
        use_chunks = (
            self.chunk_length_sec > 0
            and duration_sec >= self.chunk_min_audio_sec
        )
        if use_chunks:
            return self._transcribe_chunked(audio_data, sample_rate, language)
        return self._transcribe_single_pass(audio_data, sample_rate, language)

    def is_available(self) -> bool:
        try:
            import faster_whisper
            return True
        except ImportError:
            return False

    def get_name(self) -> str:
        return f"Whisper ({self.model_size})"

    def warmup(self) -> None:
        self._load_model()
        dummy = np.zeros(16000, dtype=np.float32)
        try:
            self.transcribe(dummy)
        except Exception:
            pass
