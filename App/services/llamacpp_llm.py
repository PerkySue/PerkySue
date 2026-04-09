"""
Backward-compat shim for older imports.

Older builds imported `services.llamacpp_llm`.
Current code lives under `services.llm.llamacpp_llm`.
"""

from .llm.llamacpp_llm import *  # noqa: F401,F403

