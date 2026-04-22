"""
Filesystem helpers for the Avatar Editor (Data/Skins character packs).

Used when the optional Data/Plugins/avatar_editor extension is installed.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any, List, Optional, Tuple

from .skin_paths import _find_tts_personality_yaml, skins_data_root

# Aligned with skin_paths._RESERVED_CHARACTER_SUBDIRS (subset for "is a character folder")
_SKIP_NAMES = frozenset({"Default", "images", "assets", "__pycache__"})

_NEW_PACK_PROMPT = """# TTS personality for this character (used when this pack is active).

prompt: |
  You are a helpful voice assistant. Keep a warm, clear tone suited for read-aloud replies.
  This shapes TTS delivery only — follow the main system prompt for facts and tasks.
"""


def sanitize_character_name(raw: str) -> Optional[str]:
    """Return safe single-segment folder name, or None if invalid."""
    s = (raw or "").strip()
    if not s or len(s) > 64:
        return None
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_\- ]{0,63}$", s):
        return None
    if s.strip(".") in _SKIP_NAMES:
        return None
    return s.replace(" ", "_")


def character_profile_path(char_dir: Path) -> Optional[Path]:
    for c in (char_dir / "images" / "profile.png", char_dir / "profile.png"):
        if c.is_file():
            return c
    return None


def list_locale_subdirs(char_dir: Path) -> List[str]:
    out: List[str] = []
    try:
        for sub in sorted(char_dir.iterdir()):
            if not sub.is_dir():
                continue
            n = sub.name
            if n.startswith(".") or n.casefold() in {x.casefold() for x in _SKIP_NAMES}:
                continue
            if n in ("images", "assets", "__pycache__"):
                continue
            out.append(n)
    except OSError:
        pass
    return out


def list_skin_characters(paths: Any) -> List[dict]:
    """
    List first-level character directories under Data/Skins (excluding obvious non-characters).

    Each item: name, path, has_profile, locales, has_personality_yaml
    """
    root = skins_data_root(paths)
    rows: List[dict] = []
    if not root.is_dir():
        return rows
    try:
        for d in sorted(root.iterdir()):
            if not d.is_dir():
                continue
            name = d.name
            if name in _SKIP_NAMES or name.startswith("."):
                continue
            locs = list_locale_subdirs(d)
            pers = _find_tts_personality_yaml(d)
            rows.append(
                {
                    "name": name,
                    "path": d,
                    "has_profile": character_profile_path(d) is not None,
                    "locales": locs,
                    "has_personality_yaml": pers is not None,
                }
            )
    except OSError:
        pass
    return rows


def personality_candidates(char_dir: Path) -> List[Tuple[Path, str]]:
    """Ordered (path, label) for editing; character root first, then locale subfolders."""
    out: List[Tuple[Path, str]] = []
    root_yaml = _find_tts_personality_yaml(char_dir)
    if root_yaml is not None:
        out.append((root_yaml, "Character root"))
    for loc in list_locale_subdirs(char_dir):
        sub = char_dir / loc
        p = _find_tts_personality_yaml(sub)
        if p is not None and p != root_yaml:
            out.append((p, f"Locale {loc}"))
    return out


def ensure_default_personality(char_dir: Path) -> Path:
    """Create character-level tts_personality.yaml if missing; return path."""
    existing = _find_tts_personality_yaml(char_dir)
    if existing is not None:
        return existing
    target = char_dir / "tts_personality.yaml"
    char_dir.mkdir(parents=True, exist_ok=True)
    target.write_text(_NEW_PACK_PROMPT, encoding="utf-8")
    return target


def create_character_pack(paths: Any, name: str) -> Tuple[bool, str]:
    """Create Data/Skins/<name>/ with minimal layout (EN locale + personality)."""
    safe = sanitize_character_name(name)
    if not safe:
        return False, "Invalid character name (use letters, numbers, spaces, hyphen; max 64)."
    char_dir = skins_data_root(paths) / safe
    if char_dir.exists():
        return False, f"Folder already exists: {char_dir.name}"
    try:
        char_dir.mkdir(parents=True, exist_ok=False)
        (char_dir / "EN").mkdir(parents=True, exist_ok=True)
        ensure_default_personality(char_dir)
    except OSError as e:
        return False, str(e)
    return True, safe


def install_profile_image(char_dir: Path, src_image: Path) -> Tuple[bool, str]:
    """Copy PNG/JPG into images/profile.png (preferred) or profile.png."""
    if not src_image.is_file():
        return False, "Source file is missing."
    ext = src_image.suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
        return False, "Please pick a PNG or JPEG image."
    img_dir = char_dir / "images"
    try:
        img_dir.mkdir(parents=True, exist_ok=True)
        dest = img_dir / "profile.png"
        if ext == ".png":
            shutil.copy2(src_image, dest)
        else:
            try:
                from PIL import Image

                im = Image.open(src_image).convert("RGBA")
                im.save(dest, "PNG")
            except Exception:
                shutil.copy2(src_image, dest)
    except OSError as e:
        return False, str(e)
    return True, str(dest)


def install_voice_sample(char_dir: Path, locale: Optional[str], src_wav: Path) -> Tuple[bool, str]:
    """
    Copy WAV into pack: locale None → character root voice_ref.wav;
    else Data/Skins/Char/Locale/audios/voice_sample/voice_sample.wav
    """
    if not src_wav.is_file():
        return False, "Source file is missing."
    if src_wav.suffix.lower() != ".wav":
        return False, "Voice sample must be a .wav file."
    try:
        if not locale:
            dest = char_dir / "voice_ref.wav"
            shutil.copy2(src_wav, dest)
            return True, str(dest)
        loc_dir = char_dir / locale
        loc_dir.mkdir(parents=True, exist_ok=True)
        vs = loc_dir / "audios" / "voice_sample"
        vs.mkdir(parents=True, exist_ok=True)
        dest = vs / "voice_sample.wav"
        shutil.copy2(src_wav, dest)
        return True, str(dest)
    except OSError as e:
        return False, str(e)


def read_text(path: Path) -> Tuple[str, Optional[str]]:
    try:
        return path.read_text(encoding="utf-8", errors="replace"), None
    except OSError as e:
        return "", str(e)


def write_text(path: Path, text: str) -> Tuple[bool, str]:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return True, ""
    except OSError as e:
        return False, str(e)
