"""
Registre des providers LLM — version portable avec llama.cpp direct et fallback serveur.
"""

import logging

from .base import LLMProvider, LLMResult
from .ollama_llm import OllamaLLM
from .openai_llm import OpenAICompatibleLLM
from .llamacpp_llm import LlamaCppLLM
from .llamacpp_server import LlamaCppServerLLM

logger = logging.getLogger("perkysue.llm")


def llama_server_reasoning_budget(llm_config: dict) -> int:
    """Maps merged llm config to llama-server ``--reasoning-budget`` (0 = off, -1 = unlimited, N > 0 = cap)."""
    if not isinstance(llm_config, dict):
        return 0
    raw = llm_config.get("thinking", "off")
    if isinstance(raw, bool):
        on = raw
    else:
        on = str(raw or "off").strip().lower() in ("on", "true", "1", "yes")
    if not on:
        return 0
    try:
        b = int(llm_config.get("thinking_budget", 512))
    except (TypeError, ValueError):
        b = 512
    return b


LLM_PROVIDERS = {
    "llamacpp": LlamaCppLLM,
    "llamacpp_server": LlamaCppServerLLM,
    "ollama": OllamaLLM,
    "openai_compatible": OpenAICompatibleLLM,
}


def create_llm_provider(config: dict) -> LLMProvider:
    """Crée un provider LLM selon la configuration."""
    provider_name = config.get("provider", "llamacpp")

    if provider_name not in LLM_PROVIDERS:
        available = ", ".join(LLM_PROVIDERS.keys())
        raise ValueError(f"Provider LLM inconnu: '{provider_name}'. Disponibles: {available}")

    cls = LLM_PROVIDERS[provider_name]

    if provider_name == "llamacpp":
        return cls(
            model_path=config.get("model"),
            models_dir=config.get("_models_dir"),
            n_gpu_layers=config.get("n_gpu_layers", -1),
            n_ctx=config.get("n_ctx", 2048),
            n_threads=config.get("n_threads", 0),
        )
    elif provider_name == "llamacpp_server":
        return cls(
            model_path=config.get("model"),
            models_dir=config.get("_models_dir"),
            n_gpu_layers=config.get("n_gpu_layers", -1),
            n_ctx=config.get("n_ctx", 2048),
            port=config.get("server_port", 8081),
            request_timeout=config.get("request_timeout", 180),
            reasoning_budget=llama_server_reasoning_budget(config),
        )
    elif provider_name == "ollama":
        return cls(
            model=config.get("model", "qwen2.5:7b"),
            base_url=config.get("base_url", "http://localhost:11434"),
        )
    elif provider_name == "openai_compatible":
        return cls(
            model=config.get("model", "local-model"),
            base_url=config.get("base_url", "http://localhost:1234/v1"),
            api_key=config.get("api_key", "not-needed"),
        )
    else:
        return cls()


def _is_rtx_50xx():
    """Détecte si une RTX 50xx est présente (RTX 5090, 5080, 5070...).
    Uses 'nvidia-smi -L' which is compatible with all driver versions.
    """
    try:
        import subprocess
        result = subprocess.run(
            ["nvidia-smi", "-L"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            return False
        gpu_output = result.stdout.lower()
        # Détecte RTX 50xx (5090, 5080, 5070, 5060, etc.)
        return any(model in gpu_output for model in ["rtx 50", "rtx 5090", "rtx 5080", "rtx 5070", "rtx 5060"])
    except Exception:
        return False


def create_llm_provider_with_fallback(config: dict):
    """
    Crée le provider avec fallback automatique sur llama-server si nécessaire.
    
    Priorité :
    1. Détection auto RTX 50xx → serveur (pour compatibilité)
    2. force_direct_mode: true → direct (override utilisateur)
    3. force_server_mode: true → serveur (override utilisateur)
    4. Mode direct par défaut, fallback sur serveur si crash
    
    Returns:
        (provider, used_fallback) où used_fallback est True si on utilise le serveur
    """
    
    # 1. Détection automatique RTX 50xx
    if _is_rtx_50xx():
        logger.info("RTX 50xx detected - using server mode for CUDA compatibility")
        # CRITICAL: RTX 50xx should use GPU via server mode, not CPU.
        # _probe_gpu() may have forced n_gpu_layers=0 because the DIRECT
        # llama-cpp-python CUDA 12.4 test fails on Blackwell GPUs.
        # But llama-server.exe from nvidia-cuda-13.1 works perfectly with GPU.
        rtx50_gpu_layers = config.get("n_gpu_layers", -1)
        if rtx50_gpu_layers == 0:
            rtx50_gpu_layers = -1  # Restore full GPU offload for server mode
            logger.info("Restored n_gpu_layers=-1 for RTX 50xx server mode (was forced to 0 by GPU probe)")
        try:
            provider = LlamaCppServerLLM(
                model_path=config.get("model"),
                models_dir=config.get("_models_dir"),
                n_gpu_layers=rtx50_gpu_layers,
                n_ctx=config.get("n_ctx", 2048),
                port=config.get("server_port", 8081),
                request_timeout=config.get("request_timeout", 180),
                reasoning_budget=llama_server_reasoning_budget(config),
            )
            return provider, True
        except Exception as e:
            logger.error(f"Auto-detected server mode failed: {e}")
            # Continue avec les autres options
    
    # 2. Override utilisateur : forcer le mode direct
    if config.get("force_direct_mode", False):
        logger.info("Direct mode forced by user configuration")
        provider = LlamaCppLLM(
            model_path=config.get("model"),
            models_dir=config.get("_models_dir"),
            n_gpu_layers=config.get("n_gpu_layers", -1),
            n_ctx=config.get("n_ctx", 2048),
            n_threads=config.get("n_threads", 0),
        )
        return provider, False
    
    # 3. Override utilisateur : forcer le mode serveur
    if config.get("force_server_mode", False):
        logger.info("Server mode forced by user configuration")
        provider = LlamaCppServerLLM(
            model_path=config.get("model"),
            models_dir=config.get("_models_dir"),
            n_gpu_layers=config.get("n_gpu_layers", -1),
            n_ctx=config.get("n_ctx", 2048),
            port=config.get("server_port", 8081),
            request_timeout=config.get("request_timeout", 180),
            reasoning_budget=llama_server_reasoning_budget(config),
        )
        return provider, True
    
    # 4. Mode direct par défaut, avec fallback sur serveur si échec
    try:
        provider = LlamaCppLLM(
            model_path=config.get("model"),
            models_dir=config.get("_models_dir"),
            n_gpu_layers=config.get("n_gpu_layers", -1),
            n_ctx=config.get("n_ctx", 2048),
            n_threads=config.get("n_threads", 0),
        )
        if provider.is_available():
            logger.info("LLM direct mode selected")
            return provider, False
    except Exception as e:
        logger.warning(f"LLM direct mode failed: {e}")
    
    # Fallback sur le serveur
    logger.info("Falling back to llama-server mode...")
    try:
        provider = LlamaCppServerLLM(
            model_path=config.get("model"),
            models_dir=config.get("_models_dir"),
            n_gpu_layers=config.get("n_gpu_layers", -1),
            n_ctx=config.get("n_ctx", 2048),
            port=config.get("server_port", 8081),
            request_timeout=config.get("request_timeout", 180),
            reasoning_budget=llama_server_reasoning_budget(config),
        )
        return provider, True
    except Exception as e:
        logger.error(f"LLM server mode also failed: {e}")
        raise RuntimeError("No LLM provider available")

__all__ = [
    "LLMProvider", "LLMResult",
    "LlamaCppLLM", "LlamaCppServerLLM", "OllamaLLM", "OpenAICompatibleLLM",
    "LLM_PROVIDERS", "create_llm_provider", "create_llm_provider_with_fallback",
    "llama_server_reasoning_budget",
]