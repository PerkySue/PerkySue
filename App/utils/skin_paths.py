"""
Skin folder layout on disk (Data/Skins) and teaser (App/Skin/Teaser).

**Current (canonical):** ``Data/Skins/<Character>/<Locale>/`` — e.g. ``Mike/FR/`` with
``profile.png``, ``audios/``, optional ``voice_ref.wav``, etc.

**Character root:** ``Data/Skins/<Character>/tts_personality.yaml`` (one personality per avatar).

**Legacy (still resolved):** ``Data/Skins/<Locale>/<Character>/`` as used before character-first layout.

**Skin id:** ``"<Character>/<Locale>"`` e.g. ``Mike/FR``. Legacy config may still store ``FR/Mike``;
``normalize_skin_id()`` maps to canonical when the matching folder exists.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterator, List, Optional, Tuple

logger = logging.getLogger("perkysue.skin_paths")

# Folder names that usually mean *locale* (not character) when guessing layout from Teaser-only trees.
_LOCALE_FOLDER_HINTS = frozenset(
    {
        "EN",
        "US",
        "GB",
        "UK",
        "FR",
        "DE",
        "ES",
        "NL",
        "IT",
        "PT",
        "JA",
        "JP",
        "KO",
        "KR",
        "ZH",
        "CN",
        "CNR",
        "HI",
        "RU",
        "ID",
        "AR",
        "BN",
    }
)

# Whisper / STT lowercase → uppercase skin pack folder hints (first match wins per Tier).
_WHISPER_TO_SKIN_LOCALES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("zh", ("ZH", "CN", "CNR")),
    ("en", ("EN", "US", "GB", "UK")),
    ("de", ("DE",)),
    ("es", ("ES",)),
    ("fr", ("FR",)),
    ("nl", ("NL",)),
    ("it", ("IT",)),
    ("pt", ("PT",)),
    ("ja", ("JA", "JP")),
    ("ko", ("KO", "KR")),
)

# PerkySue UI ``config ui.language`` → primary skin teaser folder (uppercase).
_UI_LANG_TO_SKIN_LOCALE: dict[str, str] = {
    "us": "EN",
    "gb": "EN",
    "fr": "FR",
    "de": "DE",
    "es": "ES",
    "it": "IT",
    "pt": "PT",
    "nl": "NL",
    "ja": "JA",
    "ko": "KO",
    "zh": "ZH",
    "hi": "HI",
    "ru": "RU",
    "id": "ID",
    "ar": "AR",
    "bn": "BN",
}


def split_skin_segments(skin_id: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Parse a non-Default skin id into (character, locale) **as stored** (may be legacy order).
    ``Default`` → (None, None). Bare ``Mike`` → (Mike, None).
    """
    s = (skin_id or "").strip()
    if not s or s == "Default":
        return None, None
    if "/" not in s:
        return s, None
    a, b = s.split("/", 1)
    a, b = a.strip(), b.strip()
    if not a or not b:
        return None, None
    return a, b


def skins_data_root(paths: Any) -> Path:
    return Path(paths.data) / "Skins"


def skin_dir_new_layout(paths: Any, character: str, locale: str) -> Path:
    return skins_data_root(paths) / character / locale


def skin_dir_old_layout(paths: Any, locale: str, character: str) -> Path:
    return skins_data_root(paths) / locale / character


def resolve_locale_skin_dir(paths: Any, skin_id: str) -> Optional[Path]:
    """
    Directory for this skin's locale-specific assets (audio, profile, etc.).
    Tries canonical ``Character/Locale`` first, then legacy ``Locale/Character``.
    Bare ``Character`` → ``Data/Skins/<Character>/`` if present.
    """
    a, b = split_skin_segments(skin_id)
    if not a:
        return None
    root = skins_data_root(paths)
    if not b:
        p_flat = root / a
        return p_flat if p_flat.is_dir() else None
    p_new = root / a / b
    if p_new.is_dir():
        return p_new
    p_old = root / b / a
    if p_old.is_dir():
        return p_old
    return None


def resolve_character_root(paths: Any, skin_id: str) -> Optional[Path]:
    """``Data/Skins/<Character>/`` if present (personality YAML lives here)."""
    a, b = split_skin_segments(skin_id)
    if not a or not b:
        return None
    root = skins_data_root(paths)
    cand = root / a
    if cand.is_dir():
        return cand
    cand = root / b
    if cand.is_dir():
        return cand
    return None


def normalize_skin_id(paths: Any, skin_id: str) -> str:
    """
    Return canonical ``Character/Locale``. Accepts legacy ``Locale/Character`` in config.

    Disambiguates ``Data/Skins/a/b`` using locale hints when only one path exists (old teaser UX).
    """
    s = (skin_id or "").strip() or "Default"
    if s == "Default":
        return "Default"
    a, b = split_skin_segments(s)
    if not a or not b:
        return s
    root = skins_data_root(paths)
    dir_ab = (root / a / b).is_dir()
    dir_ba = (root / b / a).is_dir()
    if dir_ab and dir_ba:
        return f"{a}/{b}"
    if dir_ab and not dir_ba:
        au, bu = a.upper(), b.upper()
        if au in _LOCALE_FOLDER_HINTS and bu not in _LOCALE_FOLDER_HINTS:
            return f"{b}/{a}"
        return f"{a}/{b}"
    if dir_ba and not dir_ab:
        return f"{b}/{a}"
    return s


def unlocked_skin(paths: Any, character: str, locale: str) -> bool:
    """True if either new or legacy folder exists on disk."""
    return skin_dir_new_layout(paths, character, locale).is_dir() or skin_dir_old_layout(
        paths, locale, character
    ).is_dir()


def skin_pack_lang_from_whisper(code: Optional[str]) -> str:
    """Map last STT language code to an uppercase teaser/pack folder key."""
    c = (code or "").strip().lower()
    if not c:
        return "EN"
    for prefix, locales in _WHISPER_TO_SKIN_LOCALES:
        if c == prefix or c.startswith(prefix + "-"):
            return locales[0]
    return c[:2].upper() if len(c) >= 2 else c.upper()


def skin_pack_lang_from_ui(ui_language: str) -> str:
    """Map Settings → UI language to uppercase skin folder key."""
    u = (ui_language or "us").strip().lower()
    return _UI_LANG_TO_SKIN_LOCALE.get(u, "EN")


def iter_existing_character_locale_dirs_for_speech(paths: Any, character: str, speech_lang: str) -> List[Path]:
    """
    Existing ``Data/Skins/<Character>/<LocaleSubdir>/`` folders to try for TTS/STT speech language.

    Order matches typical pack folder names (EN/US/GB for English, ZH/CN for Chinese, etc.).
    Only returns directories that exist on disk.
    """
    char = (character or "").strip()
    if not char:
        return []
    base = skins_data_root(paths) / char
    if not base.is_dir():
        return []
    sl = (speech_lang or "en").strip().lower()
    folder_names: List[str] = []
    for prefix, locales in _WHISPER_TO_SKIN_LOCALES:
        if sl == prefix or sl.startswith(prefix + "-"):
            folder_names.extend(locales)
            break
    else:
        if len(sl) >= 2:
            folder_names.append(sl[:2].upper())
        else:
            folder_names.append(sl.upper())

    seen: set[str] = set()
    ordered: List[Path] = []
    for fd in folder_names:
        key = fd.strip().upper()
        if key in seen:
            continue
        seen.add(key)
        p = base / fd
        if p.is_dir():
            ordered.append(p)
    return ordered


def skin_locale_codes_match(folder_lang: str, target: str) -> bool:
    """Whether a teaser folder name matches the filter target (aliases for EN, ZH, …)."""
    f = (folder_lang or "").strip().upper()
    t = (target or "").strip().upper()
    if not f or not t:
        return False
    if f == t:
        return True
    if t == "EN" and f in ("EN", "US", "GB", "UK"):
        return True
    if t in ("EN", "US", "GB", "UK") and f in ("EN", "US", "GB", "UK"):
        return True
    if t in ("ZH", "CN") and f in ("ZH", "CN", "CNR"):
        return True
    if t in ("JA", "JP") and f in ("JA", "JP"):
        return True
    if t in ("KO", "KR") and f in ("KO", "KR"):
        return True
    return False


def _canonical_character_locale_from_pair(
    data_root: Path, outer: str, inner: str
) -> Tuple[str, str]:
    """
    Decide (Character, Locale) for a teaser path ``Teaser/<outer>/<inner>/profile.png``.

    Uses ``Data/Skins`` when present; otherwise guesses from folder names (locale hints).
    """
    o, i = outer.strip(), inner.strip()
    if (data_root / o / i).is_dir():
        return o, i
    if (data_root / i / o).is_dir():
        return i, o
    ou, iu = o.upper(), i.upper()
    o_is_loc = ou in _LOCALE_FOLDER_HINTS
    i_is_loc = iu in _LOCALE_FOLDER_HINTS
    if o_is_loc and not i_is_loc:
        return i, o  # legacy Lang/Char
    if i_is_loc and not o_is_loc:
        return o, i  # new Char/Lang
    return o, i


def iter_voice_ref_pack_dirs(paths: Any) -> Iterator[Tuple[str, Path]]:
    """
    Yield ``(canonical_skin_id, pack_dir)`` for each ``voice_ref.wav`` under ``Data/Skins``.
    ``pack_dir`` is the directory containing ``voice_ref.wav`` (may be legacy or new layout).
    """
    root = skins_data_root(paths)
    if not root.is_dir():
        return iter(())
    seen: set[str] = set()
    out: List[Tuple[str, Path]] = []
    try:
        for a_dir in sorted(root.iterdir()):
            if not a_dir.is_dir():
                continue
            for b_dir in sorted(a_dir.iterdir()):
                if not b_dir.is_dir():
                    continue
                ref_wav = b_dir / "voice_ref.wav"
                if not ref_wav.is_file():
                    continue
                char, loc = _canonical_character_locale_from_pair(root, a_dir.name, b_dir.name)
                sid = f"{char}/{loc}"
                if sid in seen:
                    continue
                seen.add(sid)
                out.append((sid, b_dir))
    except OSError:
        pass
    return iter(out)


def iter_teaser_skin_entries(paths: Any) -> Iterator[Tuple[str, str, Path]]:
    """
    Yield (character, locale, profile_png_path) for each valid teaser avatar.
    Any ``Teaser/<a>/<b>/profile.png`` is canonicalized to Character/Locale using disk + hints.
    """
    teaser_root = Path(paths.app_dir) / "Skin" / "Teaser"
    if not teaser_root.is_dir():
        return iter(())

    data_root = Path(paths.data) / "Skins"
    seen: set[str] = set()
    out: List[Tuple[str, str, Path]] = []

    try:
        for a_dir in sorted(teaser_root.iterdir()):
            if not a_dir.is_dir():
                continue
            for b_dir in sorted(a_dir.iterdir()):
                if not b_dir.is_dir():
                    continue
                profile = b_dir / "profile.png"
                if not profile.is_file():
                    continue
                char, loc = _canonical_character_locale_from_pair(data_root, a_dir.name, b_dir.name)
                key = f"{char.upper()}/{loc.upper()}"
                if key in seen:
                    continue
                seen.add(key)
                out.append((char, loc, profile))
    except OSError:
        pass

    return iter(out)

