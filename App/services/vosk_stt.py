"""
Backward-compat shim for older imports.

Older builds imported `services.vosk_stt`.
Current code lives under `services.stt.vosk_stt`.
"""

from .stt.vosk_stt import *  # noqa: F401,F403

