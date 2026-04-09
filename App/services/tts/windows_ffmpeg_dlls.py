"""
Windows: TorchCodec (TorchAudio 2.9+) loads native FFmpeg DLLs when decoding/encoding.

Portable layout — PerkySue looks for a *shared* FFmpeg build (avutil/avcodec DLLs) in:
  - Python/  (same folder as python.exe)
  - Data/Tools/ffmpeg-shared/bin/

Users can drop BtbN ``*-gpl-shared`` ``bin/*.dll`` into one of these folders; we call
``os.add_dll_directory`` and prepend PATH so ``libtorchcodec*.dll`` can resolve dependencies.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any, List, Optional, Set

logger = logging.getLogger("perkysue.tts.ffmpeg_dlls")

_registered: Set[str] = set()


def _dir_has_ffmpeg_shared_dlls(d: Path) -> bool:
    if not d.is_dir():
        return False
    try:
        for p in d.iterdir():
            if not p.is_file():
                continue
            n = p.name.lower()
            if n.startswith("avutil-") and n.endswith(".dll"):
                return True
            if n.startswith("avcodec-") and n.endswith(".dll"):
                return True
    except OSError:
        return False
    return False


def portable_ffmpeg_bin_candidates(paths: Optional[Any] = None) -> List[Path]:
    """Ordered search list for FFmpeg shared ``bin`` (or flat DLL drop)."""
    out: List[Path] = []
    seen: Set[str] = set()

    def add(p: Optional[Path]) -> None:
        if p is None:
            return
        try:
            r = p.resolve()
        except OSError:
            r = p
        key = str(r).lower()
        if key in seen:
            return
        seen.add(key)
        out.append(r)

    if paths is not None:
        try:
            add(getattr(paths, "python_dir", None))
        except Exception:
            pass
        try:
            add(paths.data / "Tools" / "ffmpeg-shared" / "bin")
        except Exception:
            pass
    try:
        add(Path(sys.executable).resolve().parent)
    except Exception:
        pass
    return out


def register_portable_ffmpeg_dll_directories(paths: Optional[Any] = None) -> List[Path]:
    """Register DLL directories for this process. Safe to call multiple times."""
    if sys.platform != "win32":
        return []

    used: List[Path] = []
    for d in portable_ffmpeg_bin_candidates(paths):
        if not _dir_has_ffmpeg_shared_dlls(d):
            continue
        key = str(d.resolve())
        if key in _registered:
            used.append(d)
            continue
        try:
            os.add_dll_directory(str(d))
        except (OSError, AttributeError) as e:
            logger.warning("FFmpeg DLL dir not registered (%s): %s", d, e)
            continue
        _registered.add(key)
        prev = os.environ.get("PATH", "")
        os.environ["PATH"] = key + os.pathsep + prev
        used.append(d)
        logger.info("Portable FFmpeg DLL search path: %s", d)

    return used
