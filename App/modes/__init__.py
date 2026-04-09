"""
Mode management (LLM prompt templates).
Modes are loaded from YAML files.
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger("perkysue.modes")


@dataclass
class Mode:
    """A text processing mode."""
    id: str                    # Identifier (e.g., "transcribe", "professional")
    name: str                  # Display name (e.g., "Transcribe")
    description: str           # Short description
    needs_llm: bool            # True if mode requires an LLM
    system_prompt: str         # System prompt template
    test_inputs: dict | None = None  # Optional test samples (EN1/EN2/FR1/FR2) for GUI tests


def load_modes(modes_path: Optional[str] = None) -> dict[str, Mode]:
    """
    Load modes from YAML files.
    System modes + user overrides.
    """
    # 1. Charger les modes système
    if modes_path is None:
        system_path = Path(__file__).parent.parent / "configs" / "modes.yaml"
    else:
        system_path = Path(modes_path)
    
    modes = _load_single_file(system_path)
    system_modes_snapshot = dict(modes)  # Copie pour lire test_inputs depuis le fichier système après fusion
    
    # 2. Charger les modes utilisateur (override) — merge par champ pour ne pas perdre test_inputs
    # Résolution portable : Data/Configs/modes.yaml à côté de App/ (pas de dépendance au CWD)
    user_path = system_path.resolve().parent.parent / "Data" / "Configs" / "modes.yaml"
    if not user_path.exists():
        user_path = Path("Data/Configs/modes.yaml")  # fallback CWD-relative
    if user_path.exists():
        user_raw = _load_user_modes_raw(user_path)
        for mode_id, user_data in user_raw.items():
            if not isinstance(user_data, dict):
                continue
            sys_mode = system_modes_snapshot.get(mode_id) or modes.get(mode_id)  # Toujours préférer le snapshot système pour test_inputs
            # Merge: use user value if provided, else keep system value
            name = user_data.get("name") if user_data.get("name") is not None else (getattr(sys_mode, "name", mode_id) if sys_mode else mode_id)
            desc = user_data.get("description") if "description" in user_data else (getattr(sys_mode, "description", "") if sys_mode else "")
            needs_llm = user_data.get("needs_llm") if "needs_llm" in user_data else (getattr(sys_mode, "needs_llm", True) if sys_mode else True)
            system_prompt = user_data.get("system_prompt") if user_data.get("system_prompt") is not None else (getattr(sys_mode, "system_prompt", "") if sys_mode else "")
            ti_user = user_data.get("test_inputs")
            if isinstance(ti_user, dict) and any(str(ti_user.get(k, "") or "").strip() for k in ("EN1", "EN2", "FR1", "FR2")):
                test_inputs = _normalize_test_inputs(ti_user)
            else:
                test_inputs = getattr(system_modes_snapshot.get(mode_id), "test_inputs", None) or (getattr(sys_mode, "test_inputs", None) if sys_mode else None)
            modes[mode_id] = Mode(id=mode_id, name=name, description=desc, needs_llm=needs_llm, system_prompt=system_prompt or "", test_inputs=test_inputs)
    
    return modes


def _load_user_modes_raw(path: Path) -> dict:
    """Load raw mode dicts from user YAML (no Mode objects) for merging."""
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not data or not isinstance(data, dict):
        return {}
    return data

def _normalize_test_inputs(raw: Optional[dict]) -> Optional[dict]:
    """Normalise les clés EN1/EN2/FR1/FR2 en majuscules pour la GUI."""
    if not raw or not isinstance(raw, dict):
        return None
    out = {}
    for k, v in raw.items():
        key = str(k).strip().upper() if k else ""
        if key in ("EN1", "EN2", "FR1", "FR2"):
            out[key] = v if v is not None else ""
    return out if out else None


def _load_single_file(path: Path) -> dict[str, Mode]:
    """Helper pour charger un fichier unique."""
    if not path.exists():
        return {}
    
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    
    if not data or not isinstance(data, dict):
        return {}
    
    modes: dict[str, Mode] = {}
    for mode_id, mode_data in data.items():
        if not isinstance(mode_data, dict):
            continue
        test_inputs = _normalize_test_inputs(mode_data.get("test_inputs"))
        modes[mode_id] = Mode(
            id=mode_id,
            name=mode_data.get("name", mode_id),
            description=mode_data.get("description", ""),
            needs_llm=mode_data.get("needs_llm", True),
            system_prompt=mode_data.get("system_prompt", ""),
            test_inputs=test_inputs,
        )
    
    return modes

def render_prompt(
    mode: Mode,
    text: str,
    source_lang: str = "auto",
    target_lang: str = "en",
    selected_text: str = "",
    user_name: str = "",
    conversation_context: Optional[str] = None,
) -> str:
    """
    Render a mode's system prompt with variable substitution.

    Args:
        mode: Mode to use
        text: Transcribed text (instruction vocale)
        source_lang: Detected source language
        target_lang: Target language for translation
        selected_text: Text selected by user in the active window (optional)
        conversation_context: For Ask mode, full Q/A history to inject in system prompt so the model sees it.
    """
    prompt = mode.system_prompt or ""
    # Identity (user name) substitution (exact + spaced braces)
    user_name = (user_name or "").strip()
    uname_val = user_name or "the user"
    prompt = re.sub(r"\{\s*user_name\s*\}", uname_val, prompt, flags=re.IGNORECASE)

    # Never inject the literal "auto" into the LLM prompt (ambiguous / useless).
    sl = (source_lang or "").strip().lower()
    if sl in ("", "auto"):
        source_lang_display = (
            "not detected — respond in the same language as the user's message below"
        )
    else:
        source_lang_display = (source_lang or "").strip()

    tl = (target_lang or "en").strip()
    # All common spellings / spacing (templates from YAML, editors, etc.)
    prompt = re.sub(r"\{\s*source_lang\s*\}", source_lang_display, prompt, flags=re.IGNORECASE)
    prompt = re.sub(r"\{\s*target_lang\s*\}", tl, prompt, flags=re.IGNORECASE)

    if "{source_lang}" in prompt or re.search(r"\{\s*source_lang\s*\}", prompt, re.I):
        logger.warning(
            "render_prompt: unresolved {source_lang} after substitution (mode=%s); forcing replace",
            getattr(mode, "id", "?"),
        )
        prompt = prompt.replace("{source_lang}", source_lang_display)

    if sl in ("", "auto") and (mode.system_prompt or "").strip():
        prompt += (
            "\n\nLanguage was not detected (config or STT). "
            "You MUST infer language from the user's text and respond in that language "
            "unless they explicitly ask for another."
        )
        prompt += (
            "\nNever default to English when the user's text is clearly not English "
            "(e.g. French, Spanish). Mirror that language in your entire reply."
        )

    logger.debug(
        "render_prompt mode=%s raw_source_lang=%r display_source_lang=%r target_lang=%r "
        "still_has_placeholder=%s",
        getattr(mode, "id", "?"),
        source_lang,
        source_lang_display,
        tl,
        ("{source_lang}" in prompt) or ("{target_lang}" in prompt),
    )

    # Selected text in the active window (Smart Focus) — wording depends on mode.
    if selected_text:
        mid = (getattr(mode, "id", "") or "").strip().lower()
        if mid == "answer":
            # Ask / Alt+A: selection is reference for questions, critique, summary — not always a "rewrite only" task.
            prompt += (
                "\n\n--- SELECTED TEXT (reference) ---\n"
                "The user selected the following text in the active application. "
                "Use it as context for their spoken question or request.\n\n"
                f"{selected_text}\n"
                "--- END SELECTED TEXT ---\n\n"
                "Follow the mode rules above. If they ask for an edited or rewritten version, provide that; "
                "if they ask a question, want feedback, or analysis, answer directly — do not default to "
                "outputting only a rewritten document when they did not ask for one."
            )
        elif mid == "improve":
            # Improve / Alt+I: English instructions so STT language (e.g. en) is not biased by French framing.
            prompt += (
                "\n\n--- SELECTED TEXT ---\n"
                "The user selected the following text in the active application. "
                "The voice message describes how to edit, clean up, or replace it.\n\n"
                f"{selected_text}\n"
                "--- END SELECTED TEXT ---\n\n"
                "Apply the mode rules above. Output only the revised text (or the voice-format payload). "
                "Use the same language as the user's dictation and this selection unless they explicitly ask for another language."
            )
        else:
            # All other modes (professional, translate, email, social, …): same English framing — no French bias.
            prompt += (
                "\n\n--- SELECTED TEXT ---\n"
                "The user selected the following text in the active application. "
                "Apply the mode instructions above to this material. The voice dictation says what they want "
                "(tone, format, translation target, etc.).\n\n"
                f"{selected_text}\n"
                "--- END SELECTED TEXT ---\n\n"
                "Follow the mode rules above. Use the same language as the user's dictation and this selection "
                f"unless the mode explicitly requires another language (e.g. Translate → {tl}). "
                "Output only what the mode requires — no extra meta-commentary unless the mode allows it."
            )

    # Pour le mode Ask (Alt+A) : injecter l'historique dans le SYSTEM prompt.
    if conversation_context and conversation_context.strip():
        prompt += (
            "\n\n--- CONVERSATION SO FAR (use this to answer) ---\n"
            f"{conversation_context.strip()}\n"
            "--- END CONVERSATION ---\n\n"
            "The user message will start with 'Current question (answer this):' — you MUST answer that specific question, using the conversation above as context. "
            "Do not repeat the same generic answer for every turn; address each new question. Do NOT say the question is incomplete when the context contains the referent."
        )

    # Stable local date/time so models don't hallucinate dates, and can adapt tone ("late", "morning").
    # Keep English + ISO across all modes (most mode templates are English already).
    try:
        now = datetime.now()
        today_iso = now.strftime("%Y-%m-%d")
        time_hm = now.strftime("%H:%M")
        weekday_en = now.strftime("%A")
        prompt = (prompt or "").rstrip() + f"\n\nToday is {today_iso} ({weekday_en}), current local time is {time_hm}."
    except Exception:
        pass

    return prompt


def _default_modes() -> dict[str, Mode]:
    """Emergency fallback modes if YAML is missing."""
    return {
        "transcribe": Mode(
            id="transcribe",
            name="Transcribe",
            description="Clean up and punctuate",
            needs_llm=True,
            system_prompt=(
                "Clean up this dictated text. Fix punctuation, "
                "remove filler words. NEVER change the meaning. "
                "Return ONLY the cleaned text."
            ),
        ),
        "raw": Mode(
            id="raw",
            name="Raw",
            description="Raw transcription without LLM",
            needs_llm=False,
            system_prompt="",
        ),
    }
