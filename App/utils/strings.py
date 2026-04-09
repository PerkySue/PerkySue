"""
Lightweight i18n string loader for PerkySue GUI.
Loads one YAML file per language from App/configs/strings/<lang>.yaml.
Falls back to English if a key is missing in the active language.
"""
import yaml
from pathlib import Path

_strings: dict = {}
_fallback: dict = {}


def load_strings(lang: str = "en"):
    """Load the string file for the given language. English always loaded as fallback."""
    global _strings, _fallback
    base = Path(__file__).resolve().parent.parent / "configs" / "strings"

    # Always load English as fallback
    en_path = base / "en.yaml"
    if en_path.exists():
        with open(en_path, "r", encoding="utf-8") as f:
            _fallback = yaml.safe_load(f) or {}

    # Load requested language (may be same as English)
    lang_path = base / f"{lang}.yaml"
    if lang_path.exists():
        with open(lang_path, "r", encoding="utf-8") as f:
            _strings = yaml.safe_load(f) or {}
    else:
        _strings = _fallback


def s(path: str, default: str = "") -> str:
    """
    Get a string by dot-path. Example: s("about.hero.title") → "PerkySue"
    Falls back to English, then to default.
    """
    keys = path.split(".")
    # Try active language first
    val: object = _strings
    for k in keys:
        if isinstance(val, dict) and k in val:
            val = val[k]
        else:
            val = None
            break
    if isinstance(val, str):
        return val
    # Fallback to English
    val = _fallback
    for k in keys:
        if isinstance(val, dict) and k in val:
            val = val[k]
        else:
            return default
    return val if isinstance(val, str) else default


def s_list(path: str) -> list:
    """
    Get a list of dicts by dot-path. Example: s_list("about.use_cases.items")
    Falls back to English, then to empty list.
    """
    keys = path.split(".")
    for source in (_strings, _fallback):
        val: object = source
        for k in keys:
            if isinstance(val, dict) and k in val:
                val = val[k]
            else:
                val = None
                break
        if isinstance(val, list):
            return val
    return []


def _get_branch(root: dict, path: str) -> object:
    """Navigate dict by dot-path. Returns None if missing."""
    if not path or not isinstance(root, dict):
        return None
    val: object = root
    for k in path.split("."):
        if isinstance(val, dict) and k in val:
            val = val[k]
        else:
            return None
    return val


def _merge_i18n_values(fb: object, cur: object) -> object:
    """Merge English fallback with active language: dicts recurse; non-empty list/str wins; else fallback."""
    if isinstance(fb, dict) and isinstance(cur, dict):
        out: dict = {}
        for k in set(fb.keys()) | set(cur.keys()):
            if k in cur and k in fb:
                out[k] = _merge_i18n_values(fb[k], cur[k])
            elif k in cur:
                out[k] = cur[k]
            else:
                out[k] = fb[k]
        return out
    if isinstance(fb, list) and isinstance(cur, list) and len(cur) > 0:
        return cur
    if isinstance(cur, list) and len(cur) > 0:
        return cur
    if isinstance(fb, list):
        return fb
    if cur is not None and (not isinstance(cur, str) or str(cur).strip()):
        return cur
    return fb


def merge_strings_at(path: str) -> object:
    """
    Deep-merge a subtree from English fallback + active language (e.g. header_tips, header_alerts).
    Use for nested dicts, lists (tips), and scalars. Returns None if absent in both.
    """
    fb = _get_branch(_fallback, path)
    cur = _get_branch(_strings, path)
    if fb is None and cur is None:
        return None
    if fb is None:
        return cur
    if cur is None:
        return fb
    return _merge_i18n_values(fb, cur)
