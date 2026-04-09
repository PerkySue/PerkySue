"""
Re-export des types partagés STT pour compatibilité.
Permet à services/__init__.py d’importer depuis .base si besoin.
"""

from .stt.base import STTProvider, TranscriptionResult

__all__ = ["STTProvider", "TranscriptionResult"]
