"""
Interface abstraite pour les providers Speech-to-Text.

Pour ajouter un nouveau provider STT:
1. Créer un fichier dans ce dossier (ex: nouveau_stt.py)
2. Créer une classe qui hérite de STTProvider
3. Implémenter les méthodes transcribe() et is_available()
4. Ajouter l'import dans __init__.py
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
import numpy as np


@dataclass
class TranscriptionResult:
    """Résultat d'une transcription STT."""
    text: str                          # Texte transcrit
    language: Optional[str] = None     # Langue détectée (code ISO)
    confidence: float = 0.0            # Score de confiance (0-1)
    duration: float = 0.0              # Durée audio traitée (secondes)


class STTProvider(ABC):
    """Interface abstraite pour un provider STT."""

    @abstractmethod
    def transcribe(self, audio_data: np.ndarray, sample_rate: int = 16000,
                   language: Optional[str] = None) -> TranscriptionResult:
        """
        Transcrit un segment audio en texte.

        Args:
            audio_data: Array numpy float32, mono, normalisé [-1, 1]
            sample_rate: Taux d'échantillonnage (16000 par défaut)
            language: Code langue ISO forcé, ou None pour auto-detect

        Returns:
            TranscriptionResult avec le texte et les métadonnées
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Vérifie que le provider est installé et fonctionnel."""
        pass

    @abstractmethod
    def get_name(self) -> str:
        """Retourne le nom du provider pour l'affichage."""
        pass

    def warmup(self) -> None:
        """
        Pré-charge le modèle en mémoire (optionnel).
        Appelé au démarrage pour éviter la latence au premier appel.
        """
        pass
