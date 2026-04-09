"""
Provider LLM compatible avec l'API OpenAI.
Fonctionne avec: LM Studio, KoboldCpp, vLLM, text-generation-webui,
LocalAI, et tout serveur exposant une API /v1/chat/completions.

Peut aussi être utilisé avec le vrai OpenAI ou tout cloud compatible.
"""

import logging
import time
from typing import Optional

from .base import LLMProvider, LLMResult

logger = logging.getLogger("perkysue.llm.openai_compat")


class OpenAICompatibleLLM(LLMProvider):
    """Provider LLM via API OpenAI-compatible."""

    def __init__(self, model: str = "local-model",
                 base_url: str = "http://localhost:1234/v1",
                 api_key: str = "not-needed"):
        """
        Args:
            model: Nom/ID du modèle
            base_url: URL du serveur (doit se terminer par /v1)
            api_key: Clé API (souvent inutile pour les serveurs locaux)
        """
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def _get_client(self):
        """Crée un client OpenAI à la demande."""
        from openai import OpenAI
        return OpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=120.0,
        )

    def process(self, text: str, system_prompt: str,
                temperature: float = 0.3, max_tokens: int = 1024) -> LLMResult:
        """Envoie le texte au serveur compatible OpenAI."""
        start = time.time()
        client = self._get_client()

        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )

        result_text = response.choices[0].message.content.strip()
        duration = time.time() - start
        tokens = response.usage.total_tokens if response.usage else 0

        logger.info(f"OpenAI-compat ({self.model}): {tokens} tokens en {duration:.1f}s")

        return LLMResult(
            text=result_text,
            model=self.model,
            tokens_used=tokens,
            duration=duration,
        )

    def is_available(self) -> bool:
        """Vérifie que le serveur répond."""
        try:
            import httpx
            resp = httpx.get(f"{self.base_url}/models", timeout=5.0,
                             headers={"Authorization": f"Bearer {self.api_key}"})
            return resp.status_code == 200
        except Exception:
            return False

    def get_name(self) -> str:
        return f"OpenAI-Compatible ({self.model})"

    def list_models(self) -> list[str]:
        """Liste les modèles disponibles sur le serveur."""
        try:
            client = self._get_client()
            models = client.models.list()
            return [m.id for m in models.data]
        except Exception:
            return []
