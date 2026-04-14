"""
Reference WAV resolution for Chatterbox / OmniVoice voice cloning.

Resolution order:
1) Active non-default skin (`Character/Locale`) by speech language, then active locale folder.
2) Default built-in sample, supporting both legacy and locale-aware layouts:
   - `App/Skin/Default/audios/voice_sample/voice_sample.wav` (legacy)
   - `App/Skin/Default/<Locale>/audios/voice_sample/voice_sample.wav`
   - `App/Skins/Default/<Locale>/audios/voice_sample/voice_sample.wav`
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from .chatterbox_tts import normalize_speech_lang

try:
    from utils.skin_paths import (
        iter_existing_character_locale_dirs_for_speech,
        normalize_skin_id,
        resolve_locale_skin_dir,
        skin_locale_codes_match,
        split_skin_segments,
    )
except ImportError:  # package-relative runs
    from App.utils.skin_paths import (
        iter_existing_character_locale_dirs_for_speech,
        normalize_skin_id,
        resolve_locale_skin_dir,
        skin_locale_codes_match,
        split_skin_segments,
    )

_VOICE_SAMPLE_FIXED = "voice_sample.wav"


def _try_voice_ref_and_sample(root: Path) -> Optional[Path]:
    if not root.is_dir():
        return None
    legacy = root / "voice_ref.wav"
    if legacy.is_file():
        return legacy
    fixed = root / "audios" / "voice_sample" / _VOICE_SAMPLE_FIXED
    if fixed.is_file():
        return fixed
    return None


def _try_default_voice_sample(base_vs: Path) -> Optional[Path]:
    if not base_vs.is_dir():
        return None
    fixed = base_vs / _VOICE_SAMPLE_FIXED
    if fixed.is_file():
        return fixed
    return None


def _default_locale_folder_candidates(lang: str) -> list[str]:
    l = (lang or "en").strip().lower()
    if l.startswith("zh"):
        return ["ZH", "CN", "CNR"]
    if l.startswith("en"):
        return ["EN", "US", "GB", "UK"]
    if l.startswith("ja"):
        return ["JA", "JP"]
    if l.startswith("ko"):
        return ["KO", "KR"]
    return [l[:2].upper() if len(l) >= 2 else l.upper()]


def _try_default_locale_layout(paths: Any, lang: str) -> Optional[Path]:
    bases = [
        paths.app_dir / "Skin" / "Default",
        paths.app_dir / "Skins" / "Default",
    ]
    wanted = _default_locale_folder_candidates(lang)
    for base in bases:
        if not base.is_dir():
            continue
        # First: exact preferred aliases.
        for code in wanted:
            hit = _try_voice_ref_and_sample(base / code)
            if hit:
                return hit
        # Then: case/alias match against existing locale subdirs.
        try:
            for child in base.iterdir():
                if not child.is_dir():
                    continue
                if any(skin_locale_codes_match(child.name, code) for code in wanted):
                    hit = _try_voice_ref_and_sample(child)
                    if hit:
                        return hit
        except OSError:
            continue
    return None


def resolve_voice_sample_wav(paths: Any, skin: str, language: Optional[str]) -> Optional[Path]:
    """Return path to a WAV used as `audio_prompt_path`, or `None` for engine default voice."""
    lang = normalize_speech_lang(language or "en")
    skin = (skin or "Default").strip() or "Default"

    if skin != "Default" and "/" in skin:
        sid = normalize_skin_id(paths, skin)
        char, _loc = split_skin_segments(sid)
        if char:
            for loc_root in iter_existing_character_locale_dirs_for_speech(paths, char, lang):
                hit = _try_voice_ref_and_sample(loc_root)
                if hit:
                    return hit
        root = resolve_locale_skin_dir(paths, sid)
        if root:
            hit = _try_voice_ref_and_sample(root)
            if hit:
                return hit

    # Default voice sample: locale-aware layouts first, then fixed legacy folder.
    hit = _try_default_locale_layout(paths, lang)
    if hit:
        return hit

    for base in (
        paths.app_dir / "Skin" / "Default" / "audios" / "voice_sample",
        paths.app_dir / "Skins" / "Default" / "audios" / "voice_sample",
    ):
        hit = _try_default_voice_sample(base)
        if hit:
            return hit

    return None
