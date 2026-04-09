"""
Resolve effective LLM context (n_ctx) and max output tokens for Auto modes.

Single source of truth for:
- max_input_tokens / n_ctx == 0  → backend + RAM/VRAM heuristics
- max_output_tokens / max_tokens == 0 → fraction of effective context (room for prompt)

Used by Orchestrator (Help KB, Alt+A limits, alerts) and llama-server warmup.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict

logger = logging.getLogger("perkysue.llm_ctx")

# Base context by backend (aligned with former llamacpp_server.py table).
_CTX_BY_BACKEND: dict[str, int] = {
    "cpu": 2048,
    "vulkan": 4096,
    "nvidia-cuda-12.4": 8192,
    "nvidia-cuda-13.1": 16384,
}


def _effective_backend_string() -> str:
    """PERKYSUE_BACKEND from start.bat, or infer NVIDIA via nvidia-smi, else cpu."""
    raw = os.environ.get("PERKYSUE_BACKEND")
    if raw and str(raw).strip():
        return str(raw).strip().lower()
    try:
        from utils.nvidia_stats import get_nvidia_smi_snapshot

        snap = get_nvidia_smi_snapshot()
        if snap and int(snap.get("vram_total_mb") or 0) > 0:
            return "nvidia-cuda-12.4"
    except Exception:
        pass
    return "cpu"


def resolve_auto_n_ctx_from_env() -> int:
    """Context when user leaves Max input on Auto (0)."""
    b = _effective_backend_string()
    if b in _CTX_BY_BACKEND:
        return _CTX_BY_BACKEND[b]
    if "nvidia" in b:
        return 8192
    if "vulkan" in b:
        return 4096
    return 2048


def _ram_total_gb() -> float:
    try:
        import psutil

        return float(psutil.virtual_memory().total) / (1024**3)
    except Exception:
        return 8.0


def apply_vram_ram_caps(base_n_ctx: int) -> int:
    """Lower auto context on tight RAM/VRAM; never below 512."""
    backend = _effective_backend_string()
    out = max(512, int(base_n_ctx))

    ram_gb = _ram_total_gb()
    if ram_gb < 16.0 and "nvidia" not in backend:
        if out > 2048:
            out = 2048

    if "nvidia" in backend:
        try:
            from utils.nvidia_stats import get_nvidia_smi_snapshot

            snap = get_nvidia_smi_snapshot()
            vram_total = int(snap.get("vram_total_mb") or 0) if snap else 0
            vram_free = int(snap.get("vram_free_mb") or 0) if snap else 0
            if 0 < vram_total < 8192 and out > 4096:
                out = min(out, 4096)
            if 0 < vram_total < 6144 and out > 2048:
                out = min(out, 2048)
            if vram_free and vram_free < 2048 and out > 2048:
                out = min(out, 2048)
        except Exception as e:
            logger.debug("VRAM cap skipped: %s", e)

    return max(512, out)


def resolve_effective_n_ctx(llm: Dict[str, Any]) -> int:
    """
    User-set max_input_tokens / n_ctx if > 0; else Auto from env + caps.
    """
    raw = llm.get("max_input_tokens")
    if raw is None:
        raw = llm.get("n_ctx")
    try:
        explicit = int(raw) if raw is not None and str(raw).strip() != "" else 0
    except (TypeError, ValueError):
        explicit = 0
    if explicit > 0:
        return max(512, explicit)
    base = resolve_auto_n_ctx_from_env()
    return apply_vram_ram_caps(base)


def resolve_effective_max_output(llm: Dict[str, Any], n_ctx_effective: int) -> int:
    """
    If max_output_tokens / max_tokens > 0, use it (capped to leave headroom in n_ctx).
    If 0, Auto: scale with context, between 512 and 4096.
    """
    raw = llm.get("max_output_tokens")
    if raw is None:
        raw = llm.get("max_tokens")
    try:
        mo = int(raw) if raw is not None and str(raw).strip() != "" else 0
    except (TypeError, ValueError):
        mo = 0

    nctx = max(512, int(n_ctx_effective))
    headroom = max(256, nctx // 8)
    cap_by_window = max(256, nctx - headroom)

    if mo > 0:
        return max(256, min(mo, cap_by_window))

    # Auto: ~1/3 of context, clamped
    auto = max(512, min(4096, nctx // 3))
    return max(256, min(auto, cap_by_window))


def resolve_effective_n_ctx_for_server(initial_n_ctx: int, llm: Dict[str, Any] | None = None) -> int:
    """llama-server: if initial_n_ctx <= 0, same as full resolve with optional llm dict."""
    if initial_n_ctx and int(initial_n_ctx) > 0:
        return max(512, int(initial_n_ctx))
    return resolve_effective_n_ctx(llm or {})
