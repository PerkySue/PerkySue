"""
Interface abstraite pour les engines TTS.

Même pattern que services/stt/base.py et services/llm/base.py.
Le code vit dans App/services/tts/ — distribué avec l'app.
Les modèles se téléchargent dans Data/Models/TTS/<engine>/ à la demande.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List


@dataclass
class TTSResult:
    """Résultat d'une synthèse TTS."""
    audio: object = None               # np.ndarray float32 mono [-1,1]
    sample_rate: int = 24000           # Hz
    duration: float = 0.0              # Durée audio (secondes)
    engine: str = ""                   # Engine utilisé
    rtf: float = 0.0                   # Real-time factor (< 1 = faster than realtime)
    # True when MTL chunked audio was already played during synthesize (skip play_prepared).
    already_streamed: bool = False


@dataclass
class VoiceInfo:
    """Metadata d'une voix disponible."""
    id: str                            # Identifiant unique ("sue", "mike", "default")
    name: str                          # Nom affichable
    language: str = "en"               # Langue principale
    gender: str = "female"             # female / male / neutral
    source: str = "builtin"            # builtin / cloned / designed
    ref_audio: Optional[str] = None    # Chemin audio de référence (cloning)
    ref_transcript: Optional[str] = None  # Texte dit dans ref_audio (OmniVoice : alignement / qualité)
    preview_audio: Optional[str] = None
    skin_id: Optional[str] = None      # Lié à un skin PerkySue ("EN/Sue")


class TTSEngine(ABC):
    """Interface abstraite pour un engine TTS."""

    @abstractmethod
    def synthesize(
        self,
        text: str,
        voice: Optional[VoiceInfo] = None,
        language: Optional[str] = None,
        speed: float = 1.0,
    ) -> TTSResult:
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """True si le modèle est chargé et prêt."""
        pass

    @abstractmethod
    def get_name(self) -> str:
        pass

    def get_voices(self) -> List[VoiceInfo]:
        return []

    def get_languages(self) -> List[str]:
        return ["en"]

    def supports_cloning(self) -> bool:
        return False

    def supports_streaming(self) -> bool:
        return False

    def warmup(self) -> None:
        """Pré-charge le modèle. Appelé après install ou au boot si déjà installé."""
        pass

    def unload(self) -> None:
        """Libère VRAM/mémoire."""
        pass

    def get_vram_estimate_mb(self) -> Optional[int]:
        return None
