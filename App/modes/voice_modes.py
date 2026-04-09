"""
Optional YAML overlays: extra system instructions when Voice (TTS) is on.

Keys mirror ``modes.yaml`` mode ids (``email``, ``message``, …). See ``App/configs/voice_modes.yaml``.
User overrides: ``Data/Configs/voice_modes.yaml`` (merge by mode id).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

import yaml

logger = logging.getLogger("perkysue.voice_modes")


@dataclass(frozen=True)
class VoiceModeOverlay:
    enabled: bool
    system_prompt: str


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning("voice_modes: failed to read %s: %s", path, e)
        return {}


def load_voice_mode_overlays(system_path: Path, user_path: Optional[Path] = None) -> Dict[str, VoiceModeOverlay]:
    merged = dict(_read_yaml(system_path))
    if user_path and user_path.exists():
        user_data = _read_yaml(user_path)
        for k, v in user_data.items():
            merged[k] = v
    out: Dict[str, VoiceModeOverlay] = {}
    for mode_id, data in merged.items():
        if not isinstance(data, dict):
            continue
        mid = str(mode_id).strip()
        if not mid:
            continue
        enabled = bool(data.get("enabled", False))
        sp = (data.get("system_prompt") or "").strip()
        out[mid] = VoiceModeOverlay(enabled=enabled, system_prompt=sp)
    logger.debug(
        "voice_modes: %d mode keys after merge (system=%s, user_override=%s)",
        len(out),
        system_path,
        user_path if user_path and user_path.exists() else None,
    )
    return out
