"""
Backward-compat shim for older imports.

Older builds imported `services.whisper_stt`.
Current code lives under `services.stt.whisper_stt`.
"""

from .stt.whisper_stt import *  # noqa: F401,F403

