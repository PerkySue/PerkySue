"""
Provider STT utilisant Vosk — très léger, CPU only.
Moins précis que Whisper mais fonctionne partout sans GPU.
Utile comme fallback ou pour des machines faibles.

Installation: pip install vosk
Modèles: https://alphacephei.com/vosk/models
"""

import json
import logging
from typing import Optional
import numpy as np

from .base import STTProvider, TranscriptionResult

logger = logging.getLogger("perkysue.stt.vosk")


class VoskSTT(STTProvider):
    """Provider STT basé sur Vosk (Kaldi)."""

    # Modèles recommandés par langue
    MODEL_URLS = {
        "fr": "vosk-model-fr-0.22",
        "en": "vosk-model-en-us-0.22",
        "de": "vosk-model-de-0.21",
        "es": "vosk-model-es-0.42",
        "small-fr": "vosk-model-small-fr-0.22",
        "small-en": "vosk-model-small-en-us-0.15",
    }

    def __init__(self, model_path: Optional[str] = None, language: str = "fr"):
        """
        Args:
            model_path: Chemin vers un modèle Vosk téléchargé.
                        Si None, tente de télécharger automatiquement.
            language: Code langue pour sélection auto du modèle
        """
        self.model_path = model_path
        self.language = language
        self._model = None
        self._recognizer = None

    def _load_model(self):
        """Charge le modèle Vosk."""
        if self._model is not None:
            return

        from vosk import Model, KaldiRecognizer

        if self.model_path:
            self._model = Model(self.model_path)
        else:
            # Vosk peut télécharger automatiquement
            model_name = self.MODEL_URLS.get(self.language, self.MODEL_URLS.get("en"))
            logger.info(f"Loading Vosk model: {model_name}")
            self._model = Model(model_name=model_name)

        self._recognizer = KaldiRecognizer(self._model, 16000)
        self._recognizer.SetWords(True)
        logger.info("Modèle Vosk chargé.")

    def transcribe(self, audio_data: np.ndarray, sample_rate: int = 16000,
                   language: Optional[str] = None) -> TranscriptionResult:
        """Transcrit l'audio avec Vosk."""
        self._load_model()
        from vosk import KaldiRecognizer

        # Vosk attend du int16
        if audio_data.dtype == np.float32:
            audio_int16 = (audio_data * 32767).astype(np.int16)
        else:
            audio_int16 = audio_data.astype(np.int16)

        # Créer un nouveau recognizer pour chaque transcription
        rec = KaldiRecognizer(self._model, sample_rate)
        rec.SetWords(True)

        # Envoyer l'audio par chunks
        chunk_size = 4000
        for i in range(0, len(audio_int16), chunk_size):
            chunk = audio_int16[i:i + chunk_size].tobytes()
            rec.AcceptWaveform(chunk)

        # Résultat final
        result = json.loads(rec.FinalResult())
        text = result.get("text", "").strip()

        return TranscriptionResult(
            text=text,
            language=language or self.language,
            confidence=0.0,  # Vosk ne fournit pas de score global
            duration=len(audio_data) / sample_rate,
        )

    def is_available(self) -> bool:
        try:
            import vosk
            return True
        except ImportError:
            return False

    def get_name(self) -> str:
        return f"Vosk ({self.language})"
