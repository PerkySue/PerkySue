"""
Provider LLM utilisant llama-server (binaire C++ de llama.cpp).
Fallback quand llama-cpp-python direct échoue (problèmes CUDA threading).
"""

import logging
import os
import subprocess
import time
import requests
from pathlib import Path
from typing import Optional, Tuple

from .base import LLMProvider, LLMResult

logger = logging.getLogger("perkysue.llm.llamacpp_server")


class LlamaCppServerLLM(LLMProvider):
    """Provider LLM via llama-server (processus séparé)."""

    _RECOVERABLE_HTTP_TYPES = (
        requests.exceptions.ConnectionError,
        requests.exceptions.ChunkedEncodingError,
    )

    def __init__(self, model_path: str = None, models_dir: str = None,
                 n_gpu_layers: int = -1, n_ctx: int = 2048, port: int = 8081,
                 request_timeout: int = 120, reasoning_budget: int = 0):
        self.models_dir = Path(models_dir) if models_dir else None
        self.n_gpu_layers = n_gpu_layers
        self.n_ctx = n_ctx
        self.port = port
        try:
            rt = int(request_timeout)
        except (TypeError, ValueError):
            rt = 180
        # Base read timeout (seconds); actual POST uses (connect, read) with read boosted for huge prompts
        self.request_timeout = max(120, min(rt, 360))
        try:
            self._reasoning_budget = int(reasoning_budget)
        except (TypeError, ValueError):
            self._reasoning_budget = 0
        self._model_path = None
        self._process: Optional[subprocess.Popen] = None
        self._server_url = f"http://127.0.0.1:{port}"

        # Résoudre le chemin du modèle
        if model_path and model_path.strip():
            p = Path(model_path)
            if p.is_absolute() and p.exists():
                self._model_path = p
            elif self.models_dir:
                candidate = self.models_dir / model_path
                if candidate.exists():
                    self._model_path = candidate
        
        if not self._model_path and self.models_dir:
            # Auto-detect first GGUF
            gguf_files = sorted(self.models_dir.glob("**/*.gguf"))
            if gguf_files:
                self._model_path = gguf_files[0]
                logger.info(f"Server mode - Model auto-detected: {self._model_path.name}")

    def _find_server_binary(self) -> Optional[Path]:
        """Trouve llama-server.exe dans les sous-dossiers backend ou dans le PATH.
        
        Search order:
        1. Data/Tools/active/ (populated by start.bat)
        2. Data/Tools/{PERKYSUE_BACKEND}/ (env from start.bat)
        3. Data/Tools/{backend}/ for each known backend
        4. System PATH
        """
        # Strategy 1: Use models_dir to compute Tools path
        tools_dir = None
        if self.models_dir:
            tools_dir = self.models_dir.parent.parent / "Tools"
            logger.debug(f"Tools dir from models_dir: {tools_dir}")
        
        # Strategy 2: Use PERKYSUE_DATA env (set by start.bat and paths.py)
        if not tools_dir or not tools_dir.exists():
            data_dir = os.environ.get("PERKYSUE_DATA")
            if data_dir:
                tools_dir = Path(data_dir) / "Tools"
                logger.debug(f"Tools dir from PERKYSUE_DATA: {tools_dir}")
        
        if not tools_dir:
            logger.warning("Cannot determine Tools directory (models_dir is None and PERKYSUE_DATA not set)")
            return None
            
        if not tools_dir.exists():
            logger.warning(f"Tools directory does not exist: {tools_dir}")
            return None

        # Build search order: active first (start.bat copies the chosen backend here), then env, then fallbacks.
        # Do NOT prefer nvidia-cuda-* over active: partial or mismatched zips under Tools/ can break GPU offload
        # while active holds the working copy — that regression was seen on RTX 5090 (CPU pegged, GPU idle).
        backend_dirs = ["active"]

        env_backend = os.environ.get("PERKYSUE_BACKEND", "")
        if env_backend and env_backend not in backend_dirs:
            backend_dirs.append(env_backend)

        for b in ["nvidia-cuda-13.1", "nvidia-cuda-12.4", "vulkan", "cpu", ""]:
            if b not in backend_dirs:
                backend_dirs.append(b)

        for backend in backend_dirs:
            if backend:
                path = tools_dir / backend / "llama-server.exe"
            else:
                path = tools_dir / "llama-server.exe"
            
            if path.exists():
                logger.info(f"Found llama-server.exe in: {path.parent.name}/")
                return path
            else:
                logger.debug(f"Not found: {path}")
        
        # Chercher dans PATH
        import shutil
        server_path = shutil.which("llama-server")
        if server_path:
            logger.info(f"Found llama-server in system PATH: {server_path}")
            return Path(server_path)
        
        # Log diagnostic info for troubleshooting
        logger.error(f"llama-server.exe not found anywhere!")
        logger.error(f"  models_dir: {self.models_dir}")
        logger.error(f"  tools_dir: {tools_dir}")
        logger.error(f"  PERKYSUE_DATA: {os.environ.get('PERKYSUE_DATA', 'NOT SET')}")
        logger.error(f"  PERKYSUE_BACKEND: {os.environ.get('PERKYSUE_BACKEND', 'NOT SET')}")
        if tools_dir and tools_dir.exists():
            try:
                subdirs = [d.name for d in tools_dir.iterdir() if d.is_dir()]
                logger.error(f"  Tools subdirs: {subdirs}")
            except Exception:
                pass
        
        return None

    def _llm_server_work_dir(self) -> Path:
        """CWD for llama-server: under Data/Cache so any process CWD writes stay in the portable tree."""
        if self.models_dir:
            data_root = self.models_dir.resolve().parent.parent
        else:
            env = (os.environ.get("PERKYSUE_DATA") or "").strip()
            data_root = Path(env) if env else Path.cwd() / "Data"
        d = data_root / "Cache" / "llm_tmp"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _server_healthy(self) -> bool:
        try:
            r = requests.get(f"{self._server_url}/health", timeout=2)
            return r.status_code == 200
        except requests.exceptions.RequestException:
            return False
        except Exception:
            return False

    def _cleanup_server_process(self) -> None:
        """Stop our child llama-server if still referenced; clear handle so warmup can relaunch."""
        proc = self._process
        self._process = None
        if proc is None:
            return
        if proc.poll() is not None:
            try:
                proc.communicate(timeout=0.2)
            except Exception:
                pass
            return
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:
                pass
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        try:
            proc.communicate(timeout=0.5)
        except Exception:
            pass

    @staticmethod
    def _is_recoverable_transport_failure(exc: BaseException) -> bool:
        """True when the HTTP stack lost the server (crash, refused port, RST) — worth one restart+retry."""
        if isinstance(exc, LlamaCppServerLLM._RECOVERABLE_HTTP_TYPES):
            return True
        visited: set[int] = set()
        cur: Optional[BaseException] = exc
        while cur is not None and id(cur) not in visited:
            visited.add(id(cur))
            if isinstance(cur, (ConnectionResetError, ConnectionRefusedError, BrokenPipeError)):
                return True
            if isinstance(cur, OSError):
                if getattr(cur, "winerror", None) in (10053, 10054, 10061):
                    return True
            cur = cur.__cause__ or cur.__context__
        err = str(exc).lower()
        if "connection aborted" in err or "connection refused" in err or "10054" in err or "10061" in err:
            return True
        return False

    def warmup(self):
        """Démarre le serveur llama.cpp."""
        if self._process is not None and self._process.poll() is None and self._server_healthy():
            return

        if self._process is not None:
            if self._process.poll() is None:
                logger.warning("llama-server: child process alive but /health failed; restarting")
            else:
                logger.info("llama-server: prior process exited; launching a new server")
            self._cleanup_server_process()

        if not self._model_path or not self._model_path.exists():
            raise FileNotFoundError(f"Model not found: {self._model_path}")
        
        server_exe = self._find_server_binary()
        if not server_exe:
            raise RuntimeError(
                "llama-server.exe not found. "
                "Download it from https://github.com/ggerganov/llama.cpp/releases "
                "and place it in Data/Tools/ or in PATH."
            )
        
        # Kill any orphaned llama-server from previous sessions or start.bat
        try:
            if os.name == 'nt':
                subprocess.run(
                    ["taskkill", "/F", "/IM", "llama-server.exe"],
                    capture_output=True, timeout=5
                )
                time.sleep(0.5)
        except Exception:
            pass
        
        # Dynamic context: same rules as orchestrator (backend + RAM/VRAM caps)
        if self.n_ctx <= 0:
            from utils.llm_context_resolve import resolve_effective_n_ctx_for_server

            self.n_ctx = resolve_effective_n_ctx_for_server(self.n_ctx, {})
            logger.info(f"  Context size: {self.n_ctx} (auto)")
        
        # Construire la commande
        cmd = [
            str(server_exe),
            "-m", str(self._model_path),
            "--port", str(self.port),
            "-c", str(self.n_ctx),
            "-ngl", str(self.n_gpu_layers),
            "--host", "127.0.0.1",
            "--jinja",
            "--reasoning-format", "deepseek",
            "--reasoning-budget", str(self._reasoning_budget),
        ]

        logger.info(f"Starting llama-server on port {self.port}...")
        logger.info(f"  Binary: {server_exe}")
        logger.info(f"  Model: {self._model_path.name}")
        logger.info(f"  Context: {self.n_ctx}")
        logger.info(f"  GPU layers: {self.n_gpu_layers}")
        logger.info(f"  Reasoning budget: {self._reasoning_budget} (0=off, -1=unlimited)")

        # Démarrer le processus
        env = os.environ.copy()
        # CRITICAL: Remove CUDA_VISIBLE_DEVICES="" that _probe_gpu() may have set.
        # The server binary (e.g. nvidia-cuda-13.1) has its own CUDA runtime
        # and needs to see the GPU.
        if "CUDA_VISIBLE_DEVICES" in env:
            del env["CUDA_VISIBLE_DEVICES"]
        
        cwd = str(self._llm_server_work_dir())
        logger.debug("llama-server cwd=%s", cwd)

        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=cwd,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            env=env,
        )
        
        # Attendre que le serveur soit prêt
        if not self._wait_for_server(timeout=60):
            self._cleanup_server_process()
            raise RuntimeError("llama-server failed to start within 60 seconds")
        
        logger.info(f"llama-server ready at {self._server_url}")

    def _wait_for_server(self, timeout: int = 60) -> bool:
        """Attend que le serveur HTTP réponde."""
        start = time.time()
        while time.time() - start < timeout:
            try:
                response = requests.get(f"{self._server_url}/health", timeout=1)
                if response.status_code == 200:
                    return True
            except requests.exceptions.ConnectionError:
                pass
            except Exception:
                pass
            
            # Vérifier si le processus a crashé
            if self._process.poll() is not None:
                stdout, stderr = self._process.communicate()
                logger.error(f"llama-server exited early. stderr: {stderr[-500:]}")
                return False
            
            time.sleep(0.5)
        
        return False

    @staticmethod
    def _parse_chat_completion_choice(choice: dict) -> Tuple[str, Optional[str], str]:
        """Return (assistant_text, reasoning_for_console_or_none, text_source).

        Prefer ``message.content`` for assistant text when non-empty; populate ``reasoning_content``
        from the API when split by llama-server (``--reasoning-format deepseek``). Legacy backends
        that only expose thinking in ``content`` are handled by the client strip in the orchestrator.
        """
        if not isinstance(choice, dict):
            return "", None, "none"

        msg = choice.get("message", {}) or {}
        if not isinstance(msg, dict):
            msg = {}

        reasoning_api: Optional[str] = None
        rc = msg.get("reasoning_content")
        if isinstance(rc, str) and rc.strip():
            reasoning_api = rc.strip()

        content = msg.get("content")
        main_txt = ""
        src = "none"

        if isinstance(content, str):
            main_txt = content.strip()
            if main_txt:
                src = "message.content"
        elif isinstance(content, list):
            chunks = []
            for item in content:
                if isinstance(item, str):
                    t = item.strip()
                    if t:
                        chunks.append(t)
                elif isinstance(item, dict):
                    t = (item.get("text") or item.get("content") or "").strip()
                    if t:
                        chunks.append(t)
            if chunks:
                main_txt = "\n".join(chunks).strip()
                src = "message.content[]"

        if main_txt:
            return main_txt, reasoning_api, src

        # Empty content: some APIs put the only text in reasoning fields (legacy / misconfigured server).
        for key in ("reasoning_content", "reasoning", "thinking", "thought"):
            val = msg.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip(), None if key == "reasoning_content" else reasoning_api, f"message.{key}"

        for key in ("text", "content", "reasoning_content", "reasoning"):
            val = choice.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip(), None, f"choice.{key}"

        return "", reasoning_api, "none"

    def process(self, text: str, system_prompt: str,
                temperature: float = 0.3, max_tokens: int = 1024) -> LLMResult:
        self.warmup()

        start = time.time()
        
        # Construire le payload pour le chat completion
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ]
        
        payload = {
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        
        # Long system prompts (Help KB, Alt+A history, TTS tag appendix) + slow CPU prefill
        # can exceed a flat 120s read timeout. Add bounded extra time from payload size.
        approx_chars = len(system_prompt or "") + len(text or "")
        read_timeout = self.request_timeout + min(180, max(0, approx_chars // 20))
        read_timeout = min(read_timeout, 360)
        connect_timeout = 15

        for attempt in range(2):
            try:
                response = requests.post(
                    f"{self._server_url}/v1/chat/completions",
                    json=payload,
                    timeout=(connect_timeout, read_timeout),
                )
                response.raise_for_status()
                data = response.json()

                choice = data["choices"][0]
                result_text, reasoning_text, text_source = self._parse_chat_completion_choice(choice)
                duration = time.time() - start
                # OpenAI-compatible: "stop" = fin normale, "length" = arrêt car limite tokens (contexte ou output)
                finish_reason = choice.get("finish_reason") or None

                usage = data.get("usage", {}) or {}
                # total_tokens = prompt + completion (shared context window in llama.cpp / n_ctx)
                tokens = usage.get("total_tokens", 0) or (
                    usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
                )
                completion_tokens = usage.get("completion_tokens", 0)

                logger.info(f"llama-server: {tokens} tokens (total) in {duration:.1f}s")
                if not result_text:
                    logger.warning(
                        "llama-server returned empty assistant text (finish_reason=%r, source=%s, choice_keys=%s, message_keys=%s)",
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
                    reasoning_content=reasoning_text,
                )

            except requests.exceptions.RequestException as e:
                err_str = str(e)
                logger.error(f"llama-server request failed: {e}")
                if "timed out" in err_str.lower() or "timeout" in err_str.lower():
                    logger.warning(
                        "LLM HTTP read timed out (connect=%ss, read=%ss, ~%d prompt chars). "
                        "Raise llm.request_timeout in Settings → Performance (up to 360s) or reduce context / disable TTS prompt appendix for testing.",
                        connect_timeout,
                        read_timeout,
                        approx_chars,
                    )
                if "400" in err_str or "Bad Request" in err_str:
                    logger.warning(
                        "400 Bad Request usually means context (system + user) exceeds the model's max context. "
                        "Increase 'Max input' in Settings → Performance."
                    )
                if attempt == 0 and self._is_recoverable_transport_failure(e):
                    logger.warning("llama-server: transport error; restarting subprocess (one retry)")
                    self._cleanup_server_process()
                    try:
                        self.warmup()
                    except Exception as warm_e:
                        logger.error("llama-server restart failed: %s", warm_e)
                        raise RuntimeError(f"LLM server error: {e}") from warm_e
                    start = time.time()
                    continue
                raise RuntimeError(f"LLM server error: {e}")

    def is_available(self) -> bool:
        """Vérifie si le modèle existe et si le serveur peut démarrer."""
        if self._model_path and self._model_path.exists():
            return True
        return False

    def get_name(self) -> str:
        name = self._model_path.name if self._model_path else "no model"
        return f"llama-server ({name})"

    def list_models(self) -> list[str]:
        if not self.models_dir or not self.models_dir.exists():
            return []
        return [f.name for f in self.models_dir.glob("**/*.gguf")]

    def __del__(self):
        """Arrête le serveur proprement."""
        if self._process and self._process.poll() is None:
            logger.info("Stopping llama-server...")
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()