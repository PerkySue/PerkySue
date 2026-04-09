"""
Services TTS — synthèse vocale locale pour PerkySue.

Feature Pro opt-in : le code est toujours distribué dans App/,
mais le modèle (~1 GB) ne se télécharge que quand l'utilisateur
clique « Install » dans l'onglet Voice.

Usage depuis l'orchestrateur :
    from services.tts import TTSManager
    tts = TTSManager(models_dir=paths.models_tts, cache_dir=paths.huggingface, paths=paths)
    tts.load_config(config.get("tts", {}))
    if tts.is_installed():
        tts.load_engine()
    # ... later, in post_output hook:
    tts.speak(text="Hello world")
"""

from .base import TTSEngine, TTSResult, VoiceInfo
from .manager import TTSManager, INSTALL_NOT_INSTALLED, INSTALL_INSTALLING, INSTALL_INSTALLED, INSTALL_LOADED
from .installer import TTSInstaller

__all__ = [
    "TTSEngine", "TTSResult", "VoiceInfo",
    "TTSManager", "TTSInstaller",
    "INSTALL_NOT_INSTALLED", "INSTALL_INSTALLING", "INSTALL_INSTALLED", "INSTALL_LOADED",
]
