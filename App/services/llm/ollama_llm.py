"""
Provider LLM utilisant Ollama.
Ollama doit être installé et lancé: https://ollama.ai
Un modèle doit être téléchargé: ollama pull qwen2.5:7b
"""

import logging
import time
from typing import Optional
import httpx

from .base import LLMProvider, LLMResult

logger = logging.getLogger("perkysue.llm.ollama")


class OllamaLLM(LLMProvider):
    """Provider LLM via l'API Ollama."""

    def __init__(self, model: str = "qwen2.5:7b",
                 base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=120.0)

    def process(self, text: str, system_prompt: str,
                temperature: float = 0.3, max_tokens: int = 1024) -> LLMResult:
        """Envoie le texte à Ollama pour traitement."""
        start = time.time()

        # API Chat d'Ollama
        response = self._client.post(
            f"{self.base_url}/api/chat",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text},
                ],
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                },
            },
        )
        response.raise_for_status()
        data = response.json()

        result_text = data.get("message", {}).get("content", "").strip()
        duration = time.time() - start

        # Calculer les tokens si disponible
        tokens = 0
        if "eval_count" in data:
            tokens = data.get("prompt_eval_count", 0) + data.get("eval_count", 0)

        logger.info(f"Ollama ({self.model}): {tokens} tokens en {duration:.1f}s")

        return LLMResult(
            text=result_text,
            model=self.model,
            tokens_used=tokens,
            duration=duration,
        )

    def is_available(self) -> bool:
        """Vérifie qu'Ollama tourne et que le modèle est disponible."""
        try:
            resp = self._client.get(f"{self.base_url}/api/tags", timeout=5.0)
            if resp.status_code != 200:
                return False
            models = [m["name"] for m in resp.json().get("models", [])]
            # Vérifier que le modèle (ou une variante) est présent
            return any(self.model in m or m in self.model for m in models)
        except Exception:
            return False

    def get_name(self) -> str:
        return f"Ollama ({self.model})"

    def list_models(self) -> list[str]:
        """Liste les modèles installés dans Ollama."""
        try:
            resp = self._client.get(f"{self.base_url}/api/tags", timeout=5.0)
            resp.raise_for_status()
            return [m["name"] for m in resp.json().get("models", [])]
        except Exception:
            return []
