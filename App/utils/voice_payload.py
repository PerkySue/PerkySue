"""
Parse LLM replies that wrap injectable text in <PS_PAYLOAD>…</PS_PAYLOAD>.

Emotion tags like [laughter] stay outside the payload block so they never reach Smart Focus injection.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger("perkysue.voice_payload")

_RE_PAYLOAD_OPEN = re.compile(r"<\s*PS_PAYLOAD\s*>", re.IGNORECASE)
_RE_PAYLOAD_CLOSE = re.compile(r"<\s*/\s*PS_PAYLOAD\s*>", re.IGNORECASE)
_RE_SUBJECT = re.compile(r"<\s*PS_SUBJECT\s*>(.*?)</\s*PS_SUBJECT\s*>", re.IGNORECASE | re.DOTALL)
_RE_BODY = re.compile(r"<\s*PS_BODY\s*>(.*?)</\s*PS_BODY\s*>", re.IGNORECASE | re.DOTALL)
_RE_ANY_PS_TAG = re.compile(r"<\s*/?\s*PS_[A-Z0-9_]+\s*>", re.IGNORECASE)


@dataclass
class VoicePayloadSplit:
    """Result of splitting a voice-formatted LLM reply."""

    raw: str
    had_payload: bool
    """True if injectable structure was found (<PS_PAYLOAD>… or <PS_SUBJECT>+<PS_BODY>)."""
    injectable_plain: str
    """Text to paste into the target app (subject/body rules applied)."""
    spoken_for_tts: str
    """Text for TTS: outside-payload speech, optionally plus payload body."""


def _format_inner_for_inject(inner: str) -> str:
    inner = (inner or "").strip()
    if not inner:
        return ""
    sm = _RE_SUBJECT.search(inner)
    bm = _RE_BODY.search(inner)
    sj = sm.group(1).strip() if sm else ""
    bd = bm.group(1).strip() if bm else ""
    if sj and bd:
        return f"Subject: {sj}\n\n{bd}"
    if sj:
        return sj
    if bd:
        return bd
    cleaned = _RE_ANY_PS_TAG.sub("", inner)
    return cleaned.strip()


def _split_naked_subject_body(raw: str, *, read_aloud_payload: bool) -> VoicePayloadSplit | None:
    """Models often omit <PS_PAYLOAD> and output only <PS_SUBJECT> / <PS_BODY>."""
    sm = _RE_SUBJECT.search(raw)
    bm = _RE_BODY.search(raw)
    if not sm or not bm:
        return None
    start_i = min(sm.start(), bm.start())
    end_i = max(sm.end(), bm.end())
    inner = raw[start_i:end_i]
    injectable = _format_inner_for_inject(inner)
    if not injectable:
        return None
    before = raw[:start_i].strip()
    spoken = before
    if read_aloud_payload:
        spoken = "\n\n".join(p for p in (before, injectable) if p)
    return VoicePayloadSplit(
        raw=raw,
        had_payload=True,
        injectable_plain=injectable,
        spoken_for_tts=spoken if spoken else (injectable if read_aloud_payload else ""),
    )


def split_voice_payload_reply(raw: str, *, read_aloud_payload: bool) -> VoicePayloadSplit:
    raw = (raw or "").strip()
    if not raw:
        return VoicePayloadSplit(raw="", had_payload=False, injectable_plain="", spoken_for_tts="")

    m_open = _RE_PAYLOAD_OPEN.search(raw)
    if not m_open:
        naked = _split_naked_subject_body(raw, read_aloud_payload=read_aloud_payload)
        if naked is not None:
            return naked
        return VoicePayloadSplit(
            raw=raw,
            had_payload=False,
            injectable_plain=raw,
            spoken_for_tts=raw,
        )

    tail = raw[m_open.end() :]
    m_close = _RE_PAYLOAD_CLOSE.search(tail)
    if not m_close:
        logger.warning("Voice payload: opening <PS_PAYLOAD> without closing </PS_PAYLOAD> — fallback to full reply for inject/TTS")
        return VoicePayloadSplit(
            raw=raw,
            had_payload=False,
            injectable_plain=raw,
            spoken_for_tts=raw,
        )

    inner = tail[: m_close.start()]
    before = raw[: m_open.start()]
    after = tail[m_close.end() :]
    injectable = _format_inner_for_inject(inner)
    if not injectable:
        logger.warning("Voice payload: empty injectable inside <PS_PAYLOAD> — injection may be blank")

    # TTS: only the prelude BEFORE <PS_PAYLOAD>. Text after </PS_PAYLOAD> is often meta
    # ("Want me to adjust…") copied from examples and must not be read aloud.
    spoken = before.strip()
    if read_aloud_payload and injectable:
        spoken = "\n\n".join(p.strip() for p in (spoken, injectable) if p.strip())

    return VoicePayloadSplit(
        raw=raw,
        had_payload=True,
        injectable_plain=injectable,
        spoken_for_tts=spoken if spoken else (injectable if read_aloud_payload else ""),
    )
