"""
Registre des providers STT — version portable.
Passe les chemins Data/ aux providers.
"""

from .base import STTProvider, TranscriptionResult
from .whisper_stt import WhisperSTT
from .vosk_stt import VoskSTT

STT_PROVIDERS = {
    "whisper": WhisperSTT,
    "vosk": VoskSTT,
}


def create_stt_provider(config: dict) -> STTProvider:
    provider_name = config.get("provider", "whisper")

    if provider_name not in STT_PROVIDERS:
        available = ", ".join(STT_PROVIDERS.keys())
        raise ValueError(f"Provider STT inconnu: '{provider_name}'. Disponibles: {available}")

    cls = STT_PROVIDERS[provider_name]

    if provider_name == "whisper":
        return cls(
            model_size=config.get("model", "medium"),
            device=config.get("device", "auto"),
            compute_type=config.get("compute_type", "auto"),
            models_dir=config.get("_models_dir"),    # Injecté par Orchestrator
            cache_dir=config.get("_cache_dir"),       # Injecté par Orchestrator
            initial_prompt=config.get("initial_prompt"),  # Mots pour aider Whisper (ex. PerkySue)
            chunk_length_sec=float(config.get("chunk_length_sec") or 0.0),
            chunk_overlap_sec=float(config.get("chunk_overlap_sec", 1.0)),
            chunk_min_audio_sec=float(config.get("chunk_min_audio_sec", 45.0)),
        )
    elif provider_name == "vosk":
        return cls(
            model_path=config.get("model_path"),
            language=config.get("language", "fr"),
        )
    else:
        return cls()


__all__ = [
    "STTProvider", "TranscriptionResult",
    "WhisperSTT", "VoskSTT",
    "STT_PROVIDERS", "create_stt_provider",
]
