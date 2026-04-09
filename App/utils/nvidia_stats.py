"""
Lecture ponctuelle des stats NVIDIA via nvidia-smi (même source que la barre pipeline GUI).
Utilisé pour enrichir le prompt Help sans dépendre de l'UI.
"""

import logging
import shutil
import subprocess
from typing import Any, Optional

logger = logging.getLogger("perkysue.nvidia_stats")


def get_nvidia_smi_snapshot() -> Optional[dict[str, Any]]:
    """
    Retourne un dict avec utilisation GPU, VRAM utilisée/totale/libre, température, ou None si indisponible.
    Compatible avec les cartes NVIDIA où nvidia-smi est installé (drivers RTX, etc.).
    """
    if not shutil.which("nvidia-smi"):
        return None
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used,memory.total,memory.free,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        parts = [p.strip() for p in result.stdout.strip().split(",")]
        if len(parts) < 5:
            return None
        gpu_util = int(parts[0])
        vram_used = int(parts[1])
        vram_total = int(parts[2])
        vram_free = int(parts[3])
        temp = int(parts[4])
        vram_pct = int(vram_used / vram_total * 100) if vram_total > 0 else 0
        free_pct = int(vram_free / vram_total * 100) if vram_total > 0 else 0
        return {
            "gpu_pct": gpu_util,
            "vram_used_mb": vram_used,
            "vram_total_mb": vram_total,
            "vram_free_mb": vram_free,
            "vram_pct_used": vram_pct,
            "vram_pct_free": free_pct,
            "temp_c": temp,
        }
    except Exception as e:
        logger.debug("nvidia-smi snapshot failed: %s", e)
        return None
