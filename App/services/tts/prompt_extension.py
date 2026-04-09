"""
Build LLM system-prompt appendix for TTS tags + personality (Pro, TTS enabled).

Data sources:
  - App/configs/tts_prompt_extension.yaml (tags + default personality)
  - App/Skin/Default/tts_personality.yaml (optional override for built-in Default skin)
  - Data/Skins/<Character>/tts_personality.yaml (optional; character root)
  - Legacy: same file inside the resolved locale folder under Data/Skins/
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .chatterbox_tts import normalize_speech_lang

logger = logging.getLogger("perkysue.tts.prompt_ext")

try:
    from utils.skin_paths import resolve_locale_skin_dir, split_skin_segments
except ImportError:
    from App.utils.skin_paths import resolve_locale_skin_dir, split_skin_segments

_CHATTERBOX_ID = "chatterbox"
_OMNIVOICE_ID = "omnivoice"

_CONFIG_NAME = "tts_prompt_extension.yaml"


def _app_config_path(paths: Any) -> Path:
    return Path(paths.app_dir) / "configs" / _CONFIG_NAME


def _load_yaml_file(p: Path) -> Optional[dict]:
    if not p.is_file():
        return None
    try:
        with open(p, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else None
    except Exception as e:
        logger.warning("TTS prompt ext: failed to load %s: %s", p, e)
        return None


def load_tts_prompt_config(paths: Any) -> Dict[str, Any]:
    raw = _load_yaml_file(_app_config_path(paths))
    return raw or {}


def resolve_skin_personality_prompt(paths: Any, skin_active: str, base_cfg: Dict[str, Any]) -> str:
    """Return final personality instructions (multi-line string)."""
    default_block = base_cfg.get("default_personality") or {}
    default_prompt = (default_block.get("prompt") or "").strip()

    skin = (skin_active or "Default").strip() or "Default"
    filename = (base_cfg.get("skin_personality_filename") or "tts_personality.yaml").strip()

    candidates: list[Path] = []
    if skin != "Default" and "/" in skin:
        char, _loc = split_skin_segments(skin)
        if char:
            candidates.append(Path(paths.data) / "Skins" / char / filename)
        loc_root = resolve_locale_skin_dir(paths, skin)
        if loc_root:
            candidates.append(loc_root / filename)
    candidates.append(Path(paths.app_dir) / "Skin" / "Default" / filename)

    for p in candidates:
        data = _load_yaml_file(p)
        if not data:
            continue
        pr = (data.get("prompt") or "").strip()
        if pr:
            logger.debug("TTS personality from %s", p)
            return pr

    return default_prompt


def _format_tag_lines(items: List[Any], indent: str = "  ") -> str:
    lines = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        tag = (it.get("tag") or "").strip()
        desc = (it.get("desc") or "").strip()
        if tag:
            lines.append(f"{indent}- {tag}" + (f" — {desc}" if desc else ""))
    return "\n".join(lines)


def _format_tags_compact(items: List[Any]) -> str:
    """Space-separated tags only — minimal tokens for small LLM context."""
    parts = []
    for it in items or []:
        if isinstance(it, dict):
            t = (it.get("tag") or "").strip()
            if t:
                parts.append(t)
    return " ".join(parts)


def build_tts_llm_appendix(
    paths: Any,
    engine_id: str,
    skin_active: str,
    base_cfg: Optional[Dict[str, Any]] = None,
    reply_language: Optional[str] = None,
) -> str:
    """Markdown-style block appended to system prompt. Empty if nothing to say.

    Only the **active** engine section is included. For Chatterbox, only **Turbo** or **MTL**
    tag list is included according to ``reply_language`` (en → Turbo; else MTL).
    """
    cfg = base_cfg if base_cfg is not None else load_tts_prompt_config(paths)
    if not cfg:
        return ""

    lang = normalize_speech_lang(reply_language or "en")
    compact = cfg.get("appendix_compact_tags", True)
    if isinstance(compact, str):
        compact = compact.strip().lower() in ("1", "true", "yes", "on")

    title = (cfg.get("header_title") or "Text-to-speech").strip()
    intro = (cfg.get("intro") or "").strip()
    personality = resolve_skin_personality_prompt(paths, skin_active, cfg).strip()

    eid = (engine_id or _CHATTERBOX_ID).strip().lower()
    engines = cfg.get("engines") or {}

    parts: List[str] = [f"### {title}", ""]
    if intro:
        parts.append(intro.strip())
        parts.append("")
    if personality:
        parts.append("**Speaking personality**")
        parts.append(personality)
        parts.append("")

    if eid == _OMNIVOICE_ID:
        block = engines.get("omnivoice") or {}
        parts.append(f"**Active engine: OmniVoice** — {(block.get('summary') or '').strip()}")
        extra = (block.get("extra") or "").strip()
        if extra and not compact:
            parts.append(extra)
        tags_src = block.get("tags") or []
        if compact:
            line = _format_tags_compact(tags_src)
            if line:
                parts.append(f"**Tags** {line}")
        else:
            parts.append("**Non-verbal tags**")
            parts.append(_format_tag_lines(tags_src) or "  (none listed)")
    else:
        block = engines.get("chatterbox") or {}
        parts.append(f"**Active engine: Chatterbox** — {(block.get('summary') or '').strip()}")
        if lang == "en":
            hint = (block.get("turbo_path") or "English: Turbo tokenizer tags.").strip()
            parts.append(hint)
            tags_src = block.get("tags_turbo") or []
            label = "**Tags**"
        else:
            hint = (block.get("mtl_path") or "Non-English: MTL paralinguistic tags only.").strip()
            parts.append(hint)
            tags_src = block.get("tags_mtl_paralinguistic") or []
            label = "**Tags**"
        parts.append("")
        if compact:
            line = _format_tags_compact(tags_src)
            if line:
                parts.append(f"{label} {line}")
        else:
            parts.append(label)
            parts.append(_format_tag_lines(tags_src) or "  (none listed)")

    return "\n".join(parts).strip()
