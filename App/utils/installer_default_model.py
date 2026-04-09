"""
Resolve default GGUF for first-run download from App/configs/installer_default_models.yaml.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from utils.nvidia_stats import get_nvidia_smi_snapshot


def _load_yaml(app_configs: Path) -> dict[str, Any]:
    p = app_configs / "installer_default_models.yaml"
    if not p.is_file():
        return {}
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _nvidia_pick_model_id(raw: dict[str, Any], free_mb: int, total_mb: int) -> str | None:
    rules = ((raw.get("nvidia") or {}).get("rules")) or []
    for rule in rules:
        when = rule.get("when") or {}
        mid = rule.get("model_id")
        if not mid:
            continue
        if not when:
            return mid
        ok = True
        if "vram_free_mb_gte" in when and free_mb < int(when["vram_free_mb_gte"]):
            ok = False
        if "vram_total_mb_gte" in when and total_mb < int(when["vram_total_mb_gte"]):
            ok = False
        if "vram_free_mb_lt" in when and free_mb >= int(when["vram_free_mb_lt"]):
            ok = False
        if "vram_total_mb_lt" in when and total_mb >= int(when["vram_total_mb_lt"]):
            ok = False
        if ok:
            return mid
    return None


def _effective_backend_for_defaults() -> str:
    """
    PERKYSUE_BACKEND is set by start.bat; if the GUI is started without it
    (e.g. python App/main.py), fall back to nvidia-smi so tier rules still apply.
    """
    raw = os.environ.get("PERKYSUE_BACKEND")
    if raw is None or not str(raw).strip():
        snap = get_nvidia_smi_snapshot()
        if snap and int(snap.get("vram_total_mb") or 0) > 0:
            return "nvidia-cuda-12.4"
        return "cpu"
    return str(raw).lower().strip()


def resolve_default_model_id(app_dir: Path) -> str | None:
    """Return model id (e.g. qwen3-5-2b-base-q8) or None."""
    raw = _load_yaml(app_dir / "configs")
    fb = raw.get("fallback_no_gpu") or {}
    backend = _effective_backend_for_defaults()
    if backend == "cpu":
        return fb.get("cpu")
    if "vulkan" in backend:
        return fb.get("vulkan")
    if "nvidia" in backend:
        snap = get_nvidia_smi_snapshot()
        free_mb = int(snap.get("vram_free_mb") or 0) if snap else 0
        total_mb = int(snap.get("vram_total_mb") or 0) if snap else 0
        return _nvidia_pick_model_id(raw, free_mb, total_mb)
    return fb.get("cpu")


def resolve_default_hf_entry(paths: Any) -> dict[str, Any] | None:
    """
    Build a minimal dict for widget._start_download: repo_id, filename, name.
    Uses download_sources in installer_default_models.yaml; returns None if incomplete.
    """
    app_dir = paths.app_dir
    raw = _load_yaml(app_dir / "configs")
    mid = resolve_default_model_id(app_dir)
    if not mid:
        return None
    ds = raw.get("download_sources") or {}
    src = ds.get(mid)
    if not isinstance(src, dict):
        return None
    rid = (src.get("repo_id") or "").strip()
    fn = (src.get("filename") or "").strip()
    if not rid or not fn:
        return None
    return {
        "id": mid,
        "repo_id": rid,
        "filename": fn,
        "name": fn.replace(".gguf", "") or mid,
    }


def no_llm_hint_lines(paths: Any) -> list[str]:
    """Console lines when no LLM (aligned with installer_default_models)."""
    lines: list[str] = [
        "  In the app: Settings -> Recommended Models",
        f"  Or add a .gguf under: {paths.models_llm}",
    ]
    app_dir = paths.app_dir
    raw = _load_yaml(app_dir / "configs")
    ds = raw.get("download_sources") or {}
    mid = resolve_default_model_id(app_dir)
    if mid and isinstance(ds.get(mid), dict):
        fn = (ds[mid].get("filename") or "").strip()
        if fn:
            lines.append(f"  Default tier example: {fn}  (see App/configs/installer_default_models.yaml)")
    else:
        lines.append("  Example: Qwen3.5-2B-Base.Q8_0.gguf (Recommended Models)")
    return lines
