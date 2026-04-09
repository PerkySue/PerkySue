"""
PyTorch CUDA wheel index selection for portable PerkySue (TTS uses torch; bundle may be +cpu).

Maps ``PERKYSUE_BACKEND`` (from start.bat) to the official PyTorch extra index URL when possible.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from typing import Optional, Tuple

logger = logging.getLogger("perkysue.tts.pytorch_cuda")


def torch_gpu_runs_basic_kernels() -> bool:
    """
    True if CUDA device 0 can run a tiny matmul.

    ``torch.cuda.is_available()`` alone is not enough: e.g. RTX 5090 (sm_120 / Blackwell) may be
    visible while official PyTorch wheels only ship SASS through sm_90, causing
    "no kernel image is available for execution on the device" at runtime.
    """
    try:
        import torch

        if not torch.cuda.is_available():
            return False
        with torch.inference_mode():
            a = torch.randn(96, 96, device="cuda", dtype=torch.float16)
            b = torch.randn(96, 96, device="cuda", dtype=torch.float16)
            c = a @ b
            torch.cuda.synchronize()
            _ = float(c[0, 0].item())
        return True
    except Exception as e:
        logger.warning(
            "PyTorch CUDA kernel probe failed on device 0 (TTS will fall back to CPU): %s",
            e,
        )
        return False


def nvidia_gpu_likely_present() -> bool:
    """True if ``nvidia-smi`` is on PATH (driver installed)."""
    if not shutil.which("nvidia-smi"):
        return False
    try:
        r = subprocess.run(
            ["nvidia-smi", "-L"],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return r.returncode == 0 and (r.stdout or "").strip() != ""
    except Exception as e:
        logger.debug("nvidia-smi probe failed: %s", e)
        return False


def _parse_compute_cap(s: str) -> Optional[Tuple[int, int]]:
    t = (s or "").strip()
    if not t:
        return None
    parts = t.replace(" ", "").split(".")
    try:
        maj = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
        return maj, minor
    except (ValueError, IndexError):
        return None


def nvidia_primary_gpu_name_and_compute_cap() -> Tuple[str, Optional[Tuple[int, int]]]:
    """First GPU: marketing name and (major, minor) from ``nvidia-smi``, or ("", None)."""
    if not shutil.which("nvidia-smi"):
        return "", None
    try:
        r = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,compute_cap",
                "--format=csv,noheader",
            ],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if r.returncode != 0 or not (r.stdout or "").strip():
            return "", None
        line = (r.stdout or "").strip().splitlines()[0]
        # "NVIDIA GeForce RTX 5090, 12.0"
        bits = [x.strip() for x in line.split(",")]
        name = bits[0] if bits else ""
        cc = _parse_compute_cap(bits[1]) if len(bits) > 1 else None
        return name, cc
    except Exception as e:
        logger.debug("nvidia-smi compute_cap query failed: %s", e)
        return "", None


def nvidia_needs_pytorch_cu128() -> bool:
    """
    True if this machine likely needs PyTorch CUDA 12.8 wheels (Blackwell / sm_120).

    Official cu124 stable builds target through sm_90; RTX 50xx needs cu128 + PyTorch 2.7+.
    Updating NVIDIA drivers alone does not add missing SASS to an existing torch wheel.
    """
    name, cc = nvidia_primary_gpu_name_and_compute_cap()
    if name and re.search(r"RTX\s*50[0-9]{2}\b", name, re.IGNORECASE):
        return True
    if cc is not None:
        maj, minr = cc
        if maj > 12 or (maj == 12 and minr >= 0):
            return True
    return False


def pytorch_pip_index_url() -> Optional[str]:
    """PyTorch ``--index-url`` for pip, or None if we should not offer CUDA install."""

    import os

    if not nvidia_gpu_likely_present():
        return None

    if nvidia_needs_pytorch_cu128():
        logger.info(
            "PyTorch pip index: cu128 (Blackwell / RTX 50xx or compute_cap >= 12.0). "
            "Drivers must be recent enough for CUDA 12.8 user-mode; the wheel must match the GPU."
        )
        return "https://download.pytorch.org/whl/cu128"

    b = (os.environ.get("PERKYSUE_BACKEND") or "").strip().lower()

    if "cuda-13" in b or "cuda13" in b:
        return "https://download.pytorch.org/whl/cu124"
    if "12.4" in b or b.endswith("cuda-12.4") or "cuda-12.4" in b:
        return "https://download.pytorch.org/whl/cu124"
    if "12.1" in b or "cuda-12.1" in b:
        return "https://download.pytorch.org/whl/cu121"
    if "11.8" in b or "cu118" in b:
        return "https://download.pytorch.org/whl/cu118"

    return "https://download.pytorch.org/whl/cu124"
