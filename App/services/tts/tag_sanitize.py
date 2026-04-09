"""
Strip or whitelist TTS bracket tags ([happy], [laughter], [MOOD: x], …).

- Display / injection (unless ``feedback.debug_mode``): remove all MOOD markers and bracket tokens.
- TTS synthesis: keep only tags allowed for the active engine + speech language
  (same lists as tts_prompt_extension.yaml / prompt_extension.py).
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from .chatterbox_tts import normalize_speech_lang
from .prompt_extension import load_tts_prompt_config

_CHATTERBOX_ID = "chatterbox"
_OMNIVOICE_ID = "omnivoice"

# [MOOD: …], (MOOD: …], (MOOD: …) — models echo prompt examples or invent variants.
_RE_MOOD_BRACKET = re.compile(r"\[\s*MOOD\s*:\s*[^\]]+\]", re.IGNORECASE)
_RE_MOOD_PAREN_BRACKET_CLOSE = re.compile(r"\(\s*MOOD\s*:\s*[^\]]+\]", re.IGNORECASE)
_RE_MOOD_PAREN_CLOSE = re.compile(r"\(\s*MOOD\s*:\s*[^)]+\)", re.IGNORECASE)
# Any [ ... ] token (non-greedy inner, no nested brackets).
_RE_BRACKET = re.compile(r"\[[^\]]+\]")
# Paralinguistic block(s) at start of line/paragraph (after strip).
_RE_PARALINGUISTIC_LEAD = re.compile(r"^((?:\[[^\]]+\]\s*)+)")
# Sentence punctuation then whitespace then one or more [tags] — chunkers often split on (?<=[.!?…])\s+,
# which isolates "[sigh] …" at chunk start (OmniVoice, our Chatterbox MTL splitter). U+2060 breaks that split.
_SHIELD_BEFORE_LEADING_TAGS = re.compile(r"(?<=[.!?…])(\s+)((?:\[[^\]]+\]\s*)+)")

# Basic Markdown artifacts that should never be spoken aloud (TTS).
# Keep this conservative: strip formatting markers but keep the visible words.
_RE_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_RE_MD_CODE = re.compile(r"`{1,3}([^`]+)`{1,3}")
_RE_MD_BOLD_ITALIC = re.compile(r"(\*\*|__)(.*?)\1")
_RE_MD_ITALIC = re.compile(r"(?<!\*)\*(?!\*)([^*\n]+)(?<!\*)\*(?!\*)")
_RE_MD_UNDER = re.compile(r"(?<!_)_(?!_)([^_\n]+)(?<!_)_(?!_)")
_RE_MD_BULLET = re.compile(r"(?m)^\s*[\-\*]\s+")
_RE_MD_ENUM = re.compile(r"(?m)^\s*\d{1,3}[\.\)]\s+")
_RE_MD_ALPHA_ENUM = re.compile(r"(?m)^\s*[a-zA-Z][\.\)]\s+")
_RE_MD_HEADING = re.compile(r"(?m)^\s{0,3}#{1,6}\s+")
_RE_MD_QUOTE = re.compile(r"(?m)^\s{0,3}>\s+")
_RE_MD_FENCE = re.compile(r"(?m)^\s*```+\s*$")
_RE_MD_STRIKE = re.compile(r"~~([^~\n]+)~~")


def strip_basic_markdown_for_tts(text: str) -> str:
    """Remove common Markdown formatting so engines don't read symbols like '*' aloud."""
    if not text:
        return text
    t = text
    # Remove code fence markers but keep content.
    t = _RE_MD_FENCE.sub("", t)
    # Links: keep label only.
    t = _RE_MD_LINK.sub(r"\1", t)
    # Inline code: keep code content (no backticks).
    t = _RE_MD_CODE.sub(r"\1", t)
    # Bold/underline: keep inner text.
    t = _RE_MD_BOLD_ITALIC.sub(r"\2", t)
    # Italic: keep inner text.
    t = _RE_MD_ITALIC.sub(r"\1", t)
    t = _RE_MD_UNDER.sub(r"\1", t)
    # Strikethrough: keep inner text.
    t = _RE_MD_STRIKE.sub(r"\1", t)
    # Bullets: remove leading '-' or '*' so it's not read as "asterisk".
    t = _RE_MD_BULLET.sub("", t)
    # Enumerated lists: remove "1. " / "1) " / "a) " prefixes.
    t = _RE_MD_ENUM.sub("", t)
    t = _RE_MD_ALPHA_ENUM.sub("", t)
    # Headings / blockquotes: remove the prefix markers.
    t = _RE_MD_HEADING.sub("", t)
    t = _RE_MD_QUOTE.sub("", t)
    # Tables: pipes are often spoken ("pipe"). Replace with spaces.
    t = t.replace("|", " ")
    # As a final guard, remove stray asterisks that models may output.
    t = t.replace("*", " ")
    return re.sub(r"[ \t]{2,}", " ", t).strip()


def shield_paralinguistic_tags_for_tts_chunking(text: str) -> str:
    """
    Keep bracket emotion tags from landing alone at the start of a synthesis chunk.

    Some engines split on ``.!?…`` + whitespace; a segment like ``! [sigh] Dis-moi`` becomes a chunk
    ``[sigh] Dis-moi…`` and the tag may be read as words. Insert U+2060 (WORD JOINER) after the
    punctuation so the whitespace is not ``(?<=[.!?…])\\s+``-adjacent; tags stay with the prior clause.

    Only affects text passed to TTS (call after sanitize). Invisible in UI if applied on the synth path.
    """
    t = (text or "").strip()
    if not t:
        return t
    paras = re.split(r"\n\s*\n", t)
    merged: list[str] = []
    for para in paras:
        p = para.strip()
        if not p:
            continue
        if merged and _RE_PARALINGUISTIC_LEAD.match(p):
            merged[-1] = f"{merged[-1].rstrip()} {p}".strip()
        else:
            merged.append(p)
    shielded = [_SHIELD_BEFORE_LEADING_TAGS.sub(lambda m: "\u2060" + m.group(1) + m.group(2), block) for block in merged]
    return "\n\n".join(shielded)


def _norm_tag_inner(inner: str) -> str:
    return re.sub(r"\s+", " ", (inner or "").strip().lower())


def _allowed_tag_map(cfg: Dict[str, Any], engine_id: str, reply_language: Optional[str]) -> Dict[str, str]:
    """normalized inner -> canonical tag string from YAML (e.g. '[happy]')."""
    engines = (cfg or {}).get("engines") or {}
    eid = (engine_id or _CHATTERBOX_ID).strip().lower()
    lang = normalize_speech_lang(reply_language or "en")
    tags_src = []
    if eid == _OMNIVOICE_ID:
        block = engines.get("omnivoice") or {}
        tags_src = block.get("tags") or []
    else:
        block = engines.get("chatterbox") or {}
        if lang == "en":
            tags_src = block.get("tags_turbo") or []
        else:
            tags_src = block.get("tags_mtl_paralinguistic") or []
    out: Dict[str, str] = {}
    for it in tags_src or []:
        if not isinstance(it, dict):
            continue
        tag = (it.get("tag") or "").strip()
        if len(tag) >= 2 and tag.startswith("[") and tag.endswith("]"):
            inner = tag[1:-1]
            out[_norm_tag_inner(inner)] = tag
    return out


def strip_mood_markers(text: str) -> str:
    if not text:
        return text
    t = _RE_MOOD_BRACKET.sub(" ", text)
    t = _RE_MOOD_PAREN_BRACKET_CLOSE.sub(" ", t)
    t = _RE_MOOD_PAREN_CLOSE.sub(" ", t)
    return t


def strip_all_bracket_tags_for_display(text: str) -> str:
    """Remove MOOD markers and every [token] for Chat / Help / injection when dev plugin is off."""
    if not text:
        return text
    t = strip_mood_markers(text)
    t = _RE_BRACKET.sub(" ", t)
    lines = []
    for line in t.split("\n"):
        lines.append(re.sub(r"[ \t]{2,}", " ", line).rstrip())
    t = "\n".join(lines)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def sanitize_text_for_tts_engine(
    text: str,
    paths: Any,
    engine_id: str,
    language: Optional[str],
) -> str:
    """
    MOOD stripped; only bracket tags whitelisted for engine + language remain (canonical spelling).
    Unknown [tags] are removed. Empty-ish result collapsed.
    """
    if not text or not (text.strip()):
        return ""
    cfg = load_tts_prompt_config(paths)
    allowed = _allowed_tag_map(cfg, engine_id, language)

    t = strip_mood_markers(text)
    t = strip_basic_markdown_for_tts(t)

    def repl(m: re.Match) -> str:
        full = m.group(0)
        if len(full) < 2:
            return ""
        inner = full[1:-1]
        key = _norm_tag_inner(inner)
        if key in allowed:
            return allowed[key]
        return " "

    t = _RE_BRACKET.sub(repl, t)
    lines = []
    for line in t.split("\n"):
        lines.append(re.sub(r"[ \t]{2,}", " ", line).rstrip())
    t = "\n".join(lines)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()
