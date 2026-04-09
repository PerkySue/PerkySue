"""

Reference WAVs for Chatterbox / OmniVoice voice cloning (per locale folder).



Resolution order for Pro skins ``Character/Locale`` (e.g. active ``Mike/FR``, speech English):



1. Locale folders under the **same character** that match the **speech language** (e.g. ``Mike/EN/``):

   ``voice_ref.wav``, then ``audios/voice_sample/voice_sample.wav`` (optional ``voice_sample.txt`` beside it).

2. The **active pack folder** (e.g. ``Mike/FR``) — same.

3. ``App/Skin/Default/audios/voice_sample/voice_sample.wav`` (optional ``voice_sample.txt``).



Legacy ``Locale/Character`` on disk is still handled via ``normalize_skin_id`` /

``resolve_locale_skin_dir``.



If nothing matches, the engine uses its built-in default (not an App/Data file).

"""



from __future__ import annotations



from pathlib import Path

from typing import Any, Optional



from .chatterbox_tts import normalize_speech_lang



try:

    from utils.skin_paths import (

        normalize_skin_id,

        resolve_locale_skin_dir,

        split_skin_segments,

        iter_existing_character_locale_dirs_for_speech,

    )

except ImportError:  # package-relative runs

    from App.utils.skin_paths import (

        normalize_skin_id,

        resolve_locale_skin_dir,

        split_skin_segments,

        iter_existing_character_locale_dirs_for_speech,

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





def resolve_voice_sample_wav(paths: Any, skin: str, language: Optional[str]) -> Optional[Path]:

    """Return path to a WAV to use as ``audio_prompt_path``, or ``None`` for engine default voice."""

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



    base = paths.app_dir / "Skin" / "Default" / "audios" / "voice_sample"

    hit = _try_default_voice_sample(base)

    if hit:

        return hit

    return None
