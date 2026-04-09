"""
Sound feedback for PerkySue.
Uses winsound (Windows stdlib) — no extra dependencies.
Falls back silently on other platforms.
"""

import logging
import os
import platform
import threading

logger = logging.getLogger("perkysue.sounds")

SYSTEM = platform.system()
SOUNDS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sounds")


def _resolve(filename: str) -> str:
    """Resolve sound file path."""
    path = os.path.join(SOUNDS_DIR, filename)
    if os.path.exists(path):
        return path
    return ""


def play_async(filename: str):
    """Play a WAV file in a background thread (non-blocking)."""
    path = _resolve(filename)
    if not path:
        logger.debug(f"Sound file not found: {filename}")
        return

    def _play():
        try:
            if SYSTEM == "Windows":
                import winsound
                winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_NODEFAULT)
            else:
                # macOS / Linux fallback
                os.system(f'aplay "{path}" 2>/dev/null || afplay "{path}" 2>/dev/null &')
        except Exception as e:
            logger.debug(f"Could not play sound: {e}")

    threading.Thread(target=_play, daemon=True).start()


def play_start():
    """Play the 'listening started' sound."""
    play_async("listen_start.wav")


def play_stop():
    """Play the 'listening stopped' sound."""
    play_async("listen_stop.wav")
