"""
Provider LLM utilisant llama-cpp-python (bindings llama.cpp).
Charge les fichiers GGUF directement — aucun serveur requis.
"""

import logging
import os
import time
from pathlib import Path
from typing import Optional

from .base import LLMProvider, LLMResult

logger = logging.getLogger("perkysue.llm.llamacpp")


class LlamaCppLLM(LLMProvider):
    """Provider LLM qui charge un GGUF directement via llama.cpp."""

    def __init__(self, model_path: str = None, models_dir: str = None,
                 n_gpu_layers: int = -1, n_ctx: int = 2048, n_threads: int = 0):
        self.models_dir = Path(models_dir) if models_dir else None
        self.n_gpu_layers = n_gpu_layers
        self.n_ctx = n_ctx
        self.n_threads = n_threads
        self._model = None
        self._model_path = None

        # Résoudre le chemin du modèle
        if model_path and model_path.strip():
            p = Path(model_path)
            if p.is_absolute() and p.exists():
                self._model_path = p
            elif self.models_dir:
                candidate = self.models_dir / model_path
                if candidate.exists():
                    self._model_path = candidate
                else:
                    self._model_path = self._find_model(model_path)
        else:
            # Pas de modèle spécifié → chercher le premier GGUF dans models_dir
            self._model_path = self._find_first_model()

    def _find_first_model(self) -> Optional[Path]:
        """Trouve le premier GGUF dans models_dir."""
        if not self.models_dir or not self.models_dir.exists():
            return None
        gguf_files = sorted(self.models_dir.glob("**/*.gguf"))
        if gguf_files:
            logger.info(f"Model auto-detected: {gguf_files[0].name}")
            return gguf_files[0]
        return None

    def _find_model(self, name_hint: str) -> Optional[Path]:
        """Cherche un modèle GGUF par nom partiel dans models_dir."""
        if not self.models_dir or not self.models_dir.exists():
            return None

        hint = name_hint.lower()
        gguf_files = list(self.models_dir.glob("**/*.gguf"))

        # Match exact
        for f in gguf_files:
            if f.name.lower() == hint or f.name.lower() == hint + ".gguf":
                return f

        # Match partiel
        for f in gguf_files:
            if hint in f.name.lower():
                return f

        # Fallback: premier GGUF
        if gguf_files:
            logger.warning(f"Modèle '{name_hint}' not found, using: {gguf_files[0].name}")
            return gguf_files[0]

        return None

    def _load_model(self):
        """Load model into memory. Fallback to CPU if CUDA fails."""
        if self._model is not None:
            return

        if not self._model_path or not self._model_path.exists():
            raise FileNotFoundError(
                f"GGUF model not found: {self._model_path}\n"
                f"Download a GGUF model to: {self.models_dir}\n"
                f"Ex: https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF"
            )

        try:
            from llama_cpp import Llama
        except (ImportError, RuntimeError, OSError) as e:
            raise RuntimeError(
                f"llama-cpp-python not working: {e}\n"
                f"Try: Python\\python.exe -m pip install llama-cpp-python --force-reinstall"
            ) from e

        logger.info(f"Loading {self._model_path.name}...")
        logger.info(f"  GPU layers: {self.n_gpu_layers}, Context: {self.n_ctx}")

        try:
            self._model = Llama(
                model_path=str(self._model_path),
                n_gpu_layers=self.n_gpu_layers,
                n_ctx=self.n_ctx,
                n_threads=self.n_threads if self.n_threads > 0 else None,
                verbose=False,
            )
            logger.info(f"Model loaded: {self._model_path.name}")
        except Exception as e:
            if self.n_gpu_layers != 0:
                logger.warning(f"GPU loading failed: {e}")
                logger.warning("Fallback to CPU (n_gpu_layers=0)...")
                # CRITICAL: Hide GPU to prevent CUDA crashes even in CPU mode
                import os
                os.environ["CUDA_VISIBLE_DEVICES"] = ""
                try:
                    self._model = Llama(
                        model_path=str(self._model_path),
                        n_gpu_layers=0,
                        n_ctx=self.n_ctx,
                        n_threads=self.n_threads if self.n_threads > 0 else None,
                        verbose=False,
                    )
                    self.n_gpu_layers = 0
                    logger.info(f"Model loaded (CPU): {self._model_path.name}")
                except Exception as e2:
                    raise RuntimeError(f"Cannot load model: {e2}") from e2
            else:
                raise

    @staticmethod
    def _extract_text_from_choice(choice: dict) -> tuple[str, str]:
        """Extract assistant text from llama_cpp chat completion choice."""
        if not isinstance(choice, dict):
            return "", "none"
        msg = choice.get("message", {}) or {}
        content = msg.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip(), "message.content"
        if isinstance(content, list):
            chunks = []
            for item in content:
                if isinstance(item, str) and item.strip():
                    chunks.append(item.strip())
                elif isinstance(item, dict):
                    t = (item.get("text") or item.get("content") or "").strip()
                    if t:
                        chunks.append(t)
            if chunks:
                return "\n".join(chunks).strip(), "message.content[]"
        for key in ("reasoning_content", "reasoning", "thinking", "thought"):
            val = msg.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip(), f"message.{key}"
        return "", "none"

    def process(self, text: str, system_prompt: str,
                temperature: float = 0.3, max_tokens: int = 1024) -> LLMResult:
        self._load_model()
        start = time.time()

        # Try with system role first, fallback to merged prompt
        # (some models like Gemma 2 don't support the system role)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ]

        try:
            response = self._model.create_chat_completion(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as e:
            err_msg = str(e).lower()
            if "system" in err_msg and ("not supported" in err_msg or "role" in err_msg):
                # Model doesn't support system role — merge into user message
                logger.info("Model doesn't support system role, merging prompts")
                merged = f"{system_prompt}\n\n{text}" if system_prompt.strip() else text
                messages = [
                    {"role": "user", "content": merged},
                ]
                response = self._model.create_chat_completion(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            else:
                raise

        choice = response["choices"][0]
        result_text, text_source = self._extract_text_from_choice(choice)
        duration = time.time() - start
        finish_reason = choice.get("finish_reason") if isinstance(choice, dict) else None

        tokens = 0
        completion_tokens = 0
        if "usage" in response:
            u = response["usage"]
            tokens = u.get("total_tokens", 0)
            completion_tokens = u.get("completion_tokens", 0)

        logger.info(f"llama.cpp: {tokens} tokens in {duration:.1f}s")
        if not result_text:
            logger.warning(
                "llama.cpp returned empty assistant text (finish_reason=%r, source=%s, choice_keys=%s, message_keys=%s)",
                finish_reason,
                text_source,
                list(choice.keys()) if isinstance(choice, dict) else [],
                list((choice.get("message") or {}).keys()) if isinstance(choice, dict) else [],
            )

        return LLMResult(
            text=result_text,
            model=self._model_path.name if self._model_path else "unknown",
            tokens_used=tokens,
            completion_tokens=completion_tokens,
            duration=duration,
            finish_reason=finish_reason,
        )

    def is_available(self) -> bool:
        """Check if LLM can potentially work (model file exists).

        IMPORTANT: We do NOT import llama_cpp here. Importing it
        initializes the CUDA runtime, and if the wheel is incompatible
        with the GPU, that's a C-level crash we can't catch.
        The actual import happens in _load_model(), after we've had
        a chance to set CUDA_VISIBLE_DEVICES if needed.
        """
        if self._model_path and self._model_path.exists():
            return True

        if self.models_dir and self.models_dir.exists():
            return len(list(self.models_dir.glob("**/*.gguf"))) > 0

        return False

    def warmup(self):
        """Force load on main thread to avoid CUDA threading issues."""
        self._load_model()
        # Petite inférence pour vraiment initialiser cuBLAS
        if self._model:
            self._model("Hi", max_tokens=1)

    def get_name(self) -> str:
        name = self._model_path.name if self._model_path else "no model"
        return f"llama.cpp ({name})"

    def list_models(self) -> list[str]:
        if not self.models_dir or not self.models_dir.exists():
            return []
        return [f.name for f in self.models_dir.glob("**/*.gguf")]
