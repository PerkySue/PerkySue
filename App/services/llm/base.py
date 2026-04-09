"""
Interface abstraite pour les providers LLM (Large Language Model).

Le LLM est utilisé pour le post-processing du texte transcrit:
reformulation, traduction, nettoyage, etc.

Pour ajouter un nouveau provider LLM:
1. Créer un fichier dans ce dossier (ex: nouveau_llm.py)
2. Créer une classe qui hérite de LLMProvider
3. Implémenter les méthodes process() et is_available()
4. Ajouter l'import dans __init__.py
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class LLMResult:
    """Résultat d'un traitement LLM."""
    text: str                          # Texte généré
    model: str = ""                    # Modèle utilisé
    tokens_used: int = 0               # Tokens consommés (input + output)
    completion_tokens: int = 0         # Tokens générés en sortie (pour détecter troncature)
    duration: float = 0.0             # Temps de traitement (secondes)
    finish_reason: Optional[str] = None  # "stop" = fin normale, "length" = arrêt limite tokens (API OpenAI / llama-server)
    reasoning_content: Optional[str] = None  # Chaîne de raisonnement (llama-server + certains APIs) — pas pour injection


class LLMProvider(ABC):
    """Interface abstraite pour un provider LLM."""

    @abstractmethod
    def process(self, text: str, system_prompt: str,
                temperature: float = 0.3, max_tokens: int = 1024) -> LLMResult:
        """
        Traite du texte avec un LLM.

        Args:
            text: Texte à traiter (transcription brute)
            system_prompt: Instruction système (le mode template)
            temperature: Créativité (0.0 = déterministe)
            max_tokens: Limite de tokens en sortie

        Returns:
            LLMResult avec le texte traité
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Vérifie que le provider est accessible (serveur up, modèle chargé)."""
        pass

    @abstractmethod
    def get_name(self) -> str:
        """Retourne le nom du provider pour l'affichage."""
        pass

    def list_models(self) -> list[str]:
        """Liste les modèles disponibles (optionnel)."""
        return []
