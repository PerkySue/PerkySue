"""
TTS engine installer — handles pip install + model download.

Called from the Voice tab GUI when the user clicks "Install".
Runs in a background thread, reports progress via callbacks.

Mirrors the pattern of install.bat for backend packages,
but driven from the GUI instead of a batch script.
"""

import logging
import os
import re
import json
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Tuple

import yaml

logger = logging.getLogger("perkysue.tts.installer")

# Install states
STATE_IDLE = "idle"
STATE_PIP = "pip"            # Installing pip package
STATE_MODEL = "model"        # Downloading model weights
STATE_WARMUP = "warmup"      # Loading model into memory
STATE_DONE = "done"
STATE_ERROR = "error"
STATE_PYTORCH_CUDA = "pytorch_cuda"

# NumPy C-API / wheel mismatch (common after pulling torch + chatterbox on mixed stacks)
_NUMPY_ABI_MARKERS = (
    "numpy.dtype size changed",
    "binary incompatibility",
    "Expected 96 from C header",
    "Expected 88 from C header",
    "must rebuild for numpy",
)


def _is_numpy_abi_error(exc: BaseException) -> bool:
    parts = [f"{type(exc).__name__}: {exc}"]
    c = getattr(exc, "__cause__", None)
    if c is not None:
        parts.append(f"{type(c).__name__}: {c}")
    msg = " ".join(parts)
    return any(m in msg for m in _NUMPY_ABI_MARKERS)


def _is_torchcodec_missing_error(exc: BaseException) -> bool:
    """TorchAudio 2.8+ uses torchcodec for torchaudio.load(); cloning/reference WAV needs it."""
    parts = [f"{type(exc).__name__}: {exc}"]
    c = exc
    for _ in range(6):
        c = getattr(c, "__cause__", None) or getattr(c, "__context__", None)
        if c is None:
            break
        parts.append(f"{type(c).__name__}: {c}")
    msg = " ".join(parts).lower()
    return "torchcodec" in msg


def _is_torchvision_torch_stack_error(exc: BaseException) -> bool:
    """Torch/torchvision mismatch breaks transformers imports (e.g. OmniVoice → HiggsAudioV2TokenizerModel)."""
    parts = [f"{type(exc).__name__}: {exc}"]
    c = exc
    for _ in range(6):
        c = getattr(c, "__cause__", None) or getattr(c, "__context__", None)
        if c is None:
            break
        parts.append(f"{type(c).__name__}: {c}")
    msg = " ".join(parts)
    return any(
        m in msg
        for m in (
            "torchvision::nms",
            "operator torchvision",
            "HiggsAudioV2TokenizerModel",
            "Could not import module 'HiggsAudioV2TokenizerModel'",
        )
    )


class TTSInstaller:
    """Manages installation of TTS engines (pip + model download).

    Usage:
        installer = TTSInstaller(python_exe, models_dir)
        installer.install_chatterbox(
            on_progress=lambda state, pct, msg: update_gui(state, pct, msg),
            on_done=lambda success, error: finish(success, error),
        )
    """

    def __init__(self, python_exe: str, models_dir: Path, cache_dir: Optional[Path] = None):
        """
        Args:
            python_exe: Path to Python executable (Python/python.exe for portable)
            models_dir: Data/Models/TTS/
            cache_dir: Data/HuggingFace/ (for HF_HOME)
        """
        self.python_exe = python_exe
        self.models_dir = models_dir
        self.cache_dir = cache_dir
        self._thread: Optional[threading.Thread] = None
        self._cancel = False
        self.state = STATE_IDLE
        self._restart_required = False
        self._registry_file = self.models_dir / "registry.json"

    def _load_model_registry_spec(self) -> dict:
        app_dir = Path(__file__).resolve().parents[2]
        spec = app_dir / "configs" / "model_registry.yaml"
        if not spec.is_file():
            return {}
        try:
            obj = yaml.safe_load(spec.read_text(encoding="utf-8")) or {}
            return obj if isinstance(obj, dict) else {}
        except Exception:
            return {}

    def _model_spec_for_engine(self, engine_id: str, fallback_repo: str) -> Tuple[str, str, list]:
        spec = self._load_model_registry_spec()
        row = ((spec.get("tts_engines") or {}).get(engine_id) or {}) if isinstance(spec, dict) else {}
        repo_id = str(row.get("repo_id") or "").strip() if isinstance(row, dict) else ""
        revision = str(row.get("revision") or "").strip() if isinstance(row, dict) else ""
        allow_patterns = row.get("allow_patterns") if isinstance(row, dict) else None
        if not repo_id:
            repo_id = fallback_repo
        if not revision:
            revision = "main"
        if not isinstance(allow_patterns, list) or not allow_patterns:
            allow_patterns = ["*"]
        return repo_id, revision, [str(x) for x in allow_patterns]

    def _write_registry_entry(
        self, engine_id: str, repo_id: str, revision: str, snapshot_path: Path, reason: str
    ) -> None:
        try:
            files = [str(p.relative_to(snapshot_path)) for p in snapshot_path.rglob("*") if p.is_file()]
            if not files:
                return
            data = {"schema_version": 1, "engines": {}}
            if self._registry_file.is_file():
                try:
                    data = json.loads(self._registry_file.read_text(encoding="utf-8"))
                except Exception:
                    data = {"schema_version": 1, "engines": {}}
            if not isinstance(data, dict):
                data = {"schema_version": 1, "engines": {}}
            data.setdefault("schema_version", 1)
            data.setdefault("engines", {})
            if not isinstance(data["engines"], dict):
                data["engines"] = {}
            data["engines"][engine_id] = {
                "engine_id": engine_id,
                "repo_id": repo_id,
                "revision": revision,
                "resolved_snapshot": str(snapshot_path),
                "files": sorted(files),
                "installed_at": datetime.now(timezone.utc).isoformat(),
                "app_version": "",
                "reason": reason,
            }
            self.models_dir.mkdir(parents=True, exist_ok=True)
            self._registry_file.write_text(
                json.dumps(data, ensure_ascii=True, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("TTS installer: could not write model registry entry for %s: %s", engine_id, e)

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def cancel(self):
        self._cancel = True

    def install_chatterbox(
        self,
        on_progress: Optional[Callable[[str, int, str], None]] = None,
        on_done: Optional[Callable[[bool, str], None]] = None,
    ):
        """Install Chatterbox Turbo in a background thread.

        Args:
            on_progress: callback(state, percent_0_100, message) — called on GUI thread
            on_done: callback(success, error_message) — called on GUI thread
        """
        if self.is_running:
            logger.warning("TTS install already in progress")
            return

        self._cancel = False

        def _run():
            try:
                self._install_chatterbox_impl(on_progress)
                if on_done:
                    on_done(True, "")
            except Exception as e:
                logger.error("TTS install failed: %s", e)
                self.state = STATE_ERROR
                if on_progress:
                    on_progress(STATE_ERROR, 0, str(e))
                if on_done:
                    on_done(False, str(e))

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def install_omnivoice(
        self,
        on_progress: Optional[Callable[[str, int, str], None]] = None,
        on_done: Optional[Callable[[bool, str], None]] = None,
    ):
        """Install OmniVoice (pip + first model download) in a background thread."""
        if self.is_running:
            logger.warning("TTS install already in progress")
            return

        self._cancel = False

        def _run():
            try:
                self._install_omnivoice_impl(on_progress)
                if on_done:
                    on_done(True, "")
            except Exception as e:
                logger.error("OmniVoice install failed: %s", e)
                self.state = STATE_ERROR
                if on_progress:
                    on_progress(STATE_ERROR, 0, str(e))
                if on_done:
                    on_done(False, str(e))

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def _run_pip(
        self,
        pip_args: list,
        timeout: int = 600,
    ) -> Tuple[bool, str]:
        cmd = [self.python_exe, "-m", "pip", "install", "--break-system-packages", "--no-warn-script-location"] + pip_args
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return False, "pip timed out"
        out = ((proc.stderr or "") + "\n" + (proc.stdout or "")).strip()
        tail = out[-2500:] if len(out) > 2500 else out
        return proc.returncode == 0, tail

    def _subprocess_env(self) -> dict:
        """Environment for subprocess verification/download steps.

        Critical: keep heavy ML imports out of the running GUI process to avoid partial reload issues.
        """
        env = dict(os.environ)
        # Windows HF cache can fail on symlinks without admin privileges.
        env.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        env.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
        if self.cache_dir:
            root = str(self.cache_dir.resolve())
            env["HF_HOME"] = root
            env["HF_HUB_CACHE"] = str(self.cache_dir.resolve() / "hub")
            env["HUGGINGFACE_HUB_CACHE"] = env["HF_HUB_CACHE"]
        return env

    def _run_python(self, code: str, timeout: int = 900) -> Tuple[bool, str]:
        """Run python -c in a fresh interpreter (no in-process reload)."""
        try:
            proc = subprocess.run(
                [self.python_exe, "-c", code],
                capture_output=True,
                text=True,
                timeout=timeout,
                env=self._subprocess_env(),
            )
        except subprocess.TimeoutExpired:
            return False, "python -c timed out"
        out = ((proc.stderr or "") + "\n" + (proc.stdout or "")).strip()
        tail = out[-2500:] if len(out) > 2500 else out
        return proc.returncode == 0, tail

    def _purge_tts_extension_modules(self):
        """Drop numpy/torch/chatterbox from sys.modules so a new NumPy wheel can load (same process)."""
        drop = []
        for k in list(sys.modules):
            if k == "numpy" or k.startswith("numpy."):
                drop.append(k)
            elif k == "torch" or k.startswith("torch."):
                drop.append(k)
            elif k == "torchvision" or k.startswith("torchvision."):
                drop.append(k)
            elif k == "transformers" or k.startswith("transformers."):
                drop.append(k)
            elif k.startswith("chatterbox"):
                drop.append(k)
            elif k == "torchcodec" or k.startswith("torchcodec."):
                drop.append(k)
            elif k.startswith("omnivoice"):
                drop.append(k)
        for k in drop:
            sys.modules.pop(k, None)
        logger.info("TTS install: purged %d extension-related modules for reload", len(drop))

    @staticmethod
    def _torch_pip_index_url_from_version_string(torch_version: str) -> str:
        m = re.search(r"\+(cu\d+)", (torch_version or "").strip())
        if m:
            return f"https://download.pytorch.org/whl/{m.group(1)}"
        return "https://download.pytorch.org/whl/cpu"

    def _torch_pip_index_url_for_runtime(self) -> str:
        """PyTorch wheel index matching the installed torch build (+cpu vs +cu124, etc.)."""
        try:
            r = subprocess.run(
                [self.python_exe, "-c", "import torch; print(torch.__version__)"],
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            logger.warning("Could not run torch version probe: %s — using CPU wheel index", e)
            return "https://download.pytorch.org/whl/cpu"
        v = (r.stdout or "").strip()
        if r.returncode != 0 or not v:
            logger.warning("torch version probe failed (%s) — using CPU wheel index", (r.stderr or "")[:300])
            return "https://download.pytorch.org/whl/cpu"
        return self._torch_pip_index_url_from_version_string(v)

    @staticmethod
    def _torchvision_wheel_version_for_torch(torch_version: str) -> str:
        """Pair torchvision wheel with torch X.Y (see pytorch.org / release matrix). Avoid `torchvision --upgrade` (pulls latest torch)."""
        m = re.match(r"(\d+)\.(\d+)", (torch_version or "").strip())
        if not m:
            return "0.23.0"
        major, minor = int(m.group(1)), int(m.group(2))
        if major != 2:
            return "0.23.0"
        # torch 2.6 .. 2.11 ↔ torchvision 0.21 .. 0.26
        table = {6: "0.21.0", 7: "0.22.0", 8: "0.23.0", 9: "0.24.0", 10: "0.25.0", 11: "0.26.0"}
        return table.get(minor, "0.23.0" if minor < 9 else "0.26.0")

    def _align_torchvision_with_torch(self, on_progress, _report) -> bool:
        """Install torchvision build matching installed torch (omnivoice pins torch; stale torchvision breaks transformers)."""
        try:
            r = subprocess.run(
                [self.python_exe, "-c", "import torch; print(torch.__version__)"],
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            logger.warning("torchvision align: version probe failed: %s", e)
            return False
        tv_full = (r.stdout or "").strip()
        if r.returncode != 0 or not tv_full:
            return False
        tv_pin = self._torchvision_wheel_version_for_torch(tv_full)
        url = self._torch_pip_index_url_from_version_string(tv_full)
        _report(STATE_PIP, 12, f"Installing torchvision {tv_pin} (matches PyTorch {tv_full.split('+')[0]})...")
        logger.info(
            "TTS OmniVoice: pip install torchvision==%s --index-url %s",
            tv_pin,
            url,
        )
        ok, tail = self._run_pip(
            [f"--index-url={url}", f"torchvision=={tv_pin}"],
            timeout=600,
        )
        if not ok:
            logger.error("TTS OmniVoice: torchvision align failed: %s", tail[-1200:])
        return ok

    def _ensure_torchcodec(self, on_progress, _report) -> bool:
        """TorchAudio loads WAV via torchcodec; OmniVoice clone/ref paths call torchaudio.load."""
        try:
            import importlib.util

            if importlib.util.find_spec("torchcodec") is None:
                raise ImportError("torchcodec not found")
            import torchcodec  # noqa: F401
            return True
        except ImportError:
            pass
        _report(
            STATE_PIP,
            11,
            "Installing torchcodec (required to load reference WAV / TorchAudio)...",
        )
        logger.info("TTS OmniVoice: pip install torchcodec")
        ok, tail = self._run_pip(["torchcodec"], timeout=600)
        if not ok:
            logger.error("TTS OmniVoice: torchcodec install failed: %s", tail[-1200:])
            return False
        self._purge_tts_extension_modules()
        try:
            import torchcodec  # noqa: F401
            return True
        except ImportError:
            logger.error("TTS OmniVoice: torchcodec still not importable after pip")
            return False

    def _repair_numpy_abi(
        self,
        repair_attempt: int,
        on_progress: Optional[Callable[[str, int, str], None]],
        _report,
    ) -> bool:
        """Try to fix NumPy binary mismatch. Attempt 1: pin NumPy 1.26.x ; attempt 2: upgrade NumPy."""
        if repair_attempt == 1:
            msg = "Repairing NumPy (compatibility with ML wheels)…"
            args = ["--force-reinstall", "--no-cache-dir", "numpy>=1.26.4,<2"]
            log_hint = "pip force-reinstall numpy>=1.26.4,<2"
        else:
            msg = "Retrying NumPy upgrade (latest)…"
            args = ["--upgrade", "--force-reinstall", "--no-cache-dir", "numpy"]
            log_hint = "pip upgrade --force-reinstall numpy"

        _report(STATE_MODEL, 28, msg)
        logger.info("TTS install: %s", log_hint)
        ok, tail = self._run_pip(args, timeout=600)
        if not ok:
            logger.error("TTS install: numpy repair failed: %s", tail[-800:])
            return False
        # A NumPy ABI repair changes binary wheels. Do not attempt in-process reload.
        self._restart_required = True
        return True

    def _verify_chatterbox_import(self, on_progress, _report) -> None:
        ok, tail = self._run_python("import chatterbox; print('ok')", timeout=240)
        if not ok:
            raise ImportError(tail)

    def _download_and_verify_model(self, on_progress, _report) -> None:
        # Ensure model folder exists (some libs expect it).
        model_dir = self.models_dir / "chatterbox"
        model_dir.mkdir(parents=True, exist_ok=True)

        _report(STATE_MODEL, 30, "Downloading + verifying model (fresh process)...")
        if self._cancel:
            return

        repo_id, revision, _allow_patterns = self._model_spec_for_engine(
            "chatterbox",
            "ResembleAI/chatterbox",
        )
        code = rf"""
import os
import torch
from chatterbox.tts_turbo import ChatterboxTurboTTS
from huggingface_hub import snapshot_download
try:
    from App.services.tts.pytorch_cuda import torch_gpu_runs_basic_kernels
except Exception:
    def torch_gpu_runs_basic_kernels():
        return True

if torch.cuda.is_available() and torch_gpu_runs_basic_kernels():
    device = "cuda"
elif torch.cuda.is_available():
    device = "cpu"
elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
    device = "mps"
else:
    device = "cpu"

local_path = snapshot_download(
    repo_id={repo_id!r},
    revision={revision!r},
    allow_patterns=["*.safetensors","*.json","*.txt","*.pt","*.model"],
)
model = ChatterboxTurboTTS.from_local(local_path, device=device)
wav = model.generate("Test.")
ok = (wav is not None) and (getattr(wav, "numel", lambda: 0)() > 0)
print("ok" if ok else "empty")
"""
        ok, tail = self._run_python(code, timeout=1800)
        if not ok:
            raise RuntimeError(tail)

    def _install_chatterbox_impl(
        self,
        on_progress: Optional[Callable[[str, int, str], None]] = None,
    ):
        """Synchronous install: pip → model → warmup."""

        def _report(state: str, pct: int, msg: str):
            self.state = state
            if on_progress:
                on_progress(state, pct, msg)
            logger.info("TTS install [%s %d%%]: %s", state, pct, msg)

        # ─── Step 1: pip install chatterbox-tts (if missing) + import with NumPy ABI recovery ───
        _report(STATE_PIP, 0, "Installing chatterbox-tts package...")

        if self._cancel:
            return

        pip_done = False
        numpy_repairs_import = 0
        max_numpy_repairs = 2

        while True:
            try:
                self._verify_chatterbox_import(on_progress, _report)
                break
            except Exception as e:
                # NumPy wheel / C-API mismatch often surfaces as ImportError with chained cause
                if numpy_repairs_import < max_numpy_repairs and _is_numpy_abi_error(e):
                    numpy_repairs_import += 1
                    logger.warning(
                        "TTS install: numpy ABI issue on import (repair %d): %s",
                        numpy_repairs_import,
                        e,
                    )
                    if not self._repair_numpy_abi(numpy_repairs_import, on_progress, _report):
                        raise RuntimeError(
                            f"chatterbox import failed after NumPy repair: {e}"
                        ) from e
                    continue
                if isinstance(e, ImportError):
                    if pip_done:
                        raise RuntimeError(
                            f"pip install succeeded but chatterbox import failed: {e}"
                        ) from e
                    pip_args = [
                        self.python_exe,
                        "-m",
                        "pip",
                        "install",
                        "chatterbox-tts",
                        "--break-system-packages",
                        "--no-warn-script-location",
                    ]
                    _report(STATE_PIP, 10, "Running pip install chatterbox-tts...")
                    try:
                        proc = subprocess.run(
                            pip_args,
                            capture_output=True,
                            text=True,
                            timeout=600,
                        )
                    except subprocess.TimeoutExpired:
                        raise RuntimeError("pip install timed out (10 min)")
                    if proc.returncode != 0:
                        stderr = (proc.stderr or "").strip()
                        err_lines = [ln for ln in stderr.splitlines() if ln.strip()]
                        err_msg = err_lines[-1] if err_lines else f"pip exit code {proc.returncode}"
                        raise RuntimeError(f"pip install failed: {err_msg}")
                    pip_done = True
                    continue
                raise RuntimeError(f"chatterbox import failed: {e}") from e

        if pip_done:
            _report(STATE_PIP, 100, "chatterbox-tts installed successfully")
        else:
            _report(STATE_PIP, 100, "chatterbox-tts already installed")

        if self._cancel:
            return

        # ─── Step 2: Download model weights ───
        _report(STATE_MODEL, 0, "Downloading Chatterbox Turbo model (~1 GB)...")

        numpy_repairs_model = 0
        max_numpy_repairs_model = 2
        while True:
            try:
                self._download_and_verify_model(on_progress, _report)
                break
            except Exception as e:
                if numpy_repairs_model < max_numpy_repairs_model and _is_numpy_abi_error(e):
                    numpy_repairs_model += 1
                    logger.warning(
                        "TTS install: numpy ABI issue on model load (repair %d): %s",
                        numpy_repairs_model,
                        e,
                    )
                    if not self._repair_numpy_abi(numpy_repairs_model, on_progress, _report):
                        raise RuntimeError(
                            f"Model download/load failed after NumPy repair: {e}"
                        ) from e
                    try:
                        self._verify_chatterbox_import(on_progress, _report)
                    except Exception as e2:
                        raise RuntimeError(f"After NumPy repair, chatterbox import failed: {e2}") from e2
                    continue
                raise RuntimeError(f"Model download/load failed: {e}") from e

        if self._restart_required:
            _report(STATE_DONE, 100, "Installation complete — please restart PerkySue to finish setup.")
        else:
            _report(STATE_DONE, 100, "Installation complete — engine loads from the Voice tab.")
        try:
            from huggingface_hub import snapshot_download

            repo_id, revision, allow_patterns = self._model_spec_for_engine(
                "chatterbox",
                "ResembleAI/chatterbox",
            )
            local_snapshot = Path(
                snapshot_download(
                    repo_id=repo_id,
                    revision=revision,
                    allow_patterns=allow_patterns,
                    cache_dir=str((self.cache_dir.resolve() / "hub")) if self.cache_dir else None,
                    local_files_only=True,
                )
            )
            self._write_registry_entry(
                engine_id="chatterbox",
                repo_id=repo_id,
                revision=revision,
                snapshot_path=local_snapshot,
                reason="installer_verify",
            )
        except Exception as e:
            logger.warning("TTS installer: chatterbox registry refresh skipped: %s", e)

    def _verify_omnivoice_import(self, on_progress, _report) -> None:
        import importlib
        if "omnivoice" in sys.modules:
            del sys.modules["omnivoice"]
        import omnivoice  # noqa: F401

    def _download_and_verify_omnivoice(self, on_progress, _report) -> None:
        import os

        from .omnivoice_tts import _apply_hf_cache

        _apply_hf_cache(self.cache_dir)
        import torch
        from huggingface_hub import snapshot_download
        from omnivoice import OmniVoice

        if torch.cuda.is_available():
            device_map = "cuda:0"
            torch_dtype = torch.float16
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            device_map = "mps"
            torch_dtype = torch.float32
        else:
            device_map = "cpu"
            torch_dtype = torch.float32

        _report(STATE_MODEL, 40, "Downloading OmniVoice weights (first run may take several minutes)...")

        if self._cancel:
            return

        repo_id, revision, allow_patterns = self._model_spec_for_engine(
            "omnivoice",
            "k2-fsa/OmniVoice",
        )
        local_snapshot = Path(
            snapshot_download(
                repo_id=repo_id,
                revision=revision,
                allow_patterns=allow_patterns,
                cache_dir=str((self.cache_dir.resolve() / "hub")) if self.cache_dir else None,
            )
        )
        model = OmniVoice.from_pretrained(
            str(local_snapshot),
            torch_dtype=torch_dtype,
            device_map=device_map,
        )
        _report(STATE_MODEL, 85, "Generating test audio...")
        audios = model.generate(text="Test.", language="en", num_step=16)
        if not audios or audios[0] is None or audios[0].numel() == 0:
            raise RuntimeError("OmniVoice generate returned empty audio")

        del model
        del audios
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        self._write_registry_entry(
            engine_id="omnivoice",
            repo_id=repo_id,
            revision=revision,
            snapshot_path=local_snapshot,
            reason="installer_verify",
        )

    def _install_omnivoice_impl(
        self,
        on_progress: Optional[Callable[[str, int, str], None]] = None,
    ):
        def _report(state: str, pct: int, msg: str):
            self.state = state
            if on_progress:
                on_progress(state, pct, msg)
            logger.info("TTS OmniVoice install [%s %d%%]: %s", state, pct, msg)

        _report(STATE_PIP, 0, "Installing omnivoice package...")

        if self._cancel:
            return

        pip_done = False
        numpy_repairs_import = 0
        max_numpy_repairs = 2
        torchvision_repairs = 0
        max_torchvision_repairs = 2
        torchcodec_repairs_import = 0
        max_torchcodec_repairs_import = 2

        while True:
            try:
                self._verify_omnivoice_import(on_progress, _report)
                break
            except Exception as e:
                if numpy_repairs_import < max_numpy_repairs and _is_numpy_abi_error(e):
                    numpy_repairs_import += 1
                    logger.warning(
                        "OmniVoice install: numpy ABI issue on import (repair %d): %s",
                        numpy_repairs_import,
                        e,
                    )
                    if not self._repair_numpy_abi(numpy_repairs_import, on_progress, _report):
                        raise RuntimeError(f"omnivoice import failed after NumPy repair: {e}") from e
                    continue
                if torchvision_repairs < max_torchvision_repairs and _is_torchvision_torch_stack_error(e):
                    torchvision_repairs += 1
                    logger.warning(
                        "OmniVoice install: torch/torchvision/transformers stack repair (%d): %s",
                        torchvision_repairs,
                        e,
                    )
                    self._align_torchvision_with_torch(on_progress, _report)
                    self._purge_tts_extension_modules()
                    continue
                if torchcodec_repairs_import < max_torchcodec_repairs_import and _is_torchcodec_missing_error(e):
                    torchcodec_repairs_import += 1
                    logger.warning(
                        "OmniVoice install: torchcodec repair (%d): %s",
                        torchcodec_repairs_import,
                        e,
                    )
                    if self._ensure_torchcodec(on_progress, _report):
                        continue
                if isinstance(e, ImportError):
                    if pip_done:
                        raise RuntimeError(f"pip install succeeded but omnivoice import failed: {e}") from e
                    pip_args = [
                        self.python_exe,
                        "-m",
                        "pip",
                        "install",
                        "omnivoice",
                        "--break-system-packages",
                        "--no-warn-script-location",
                    ]
                    _report(STATE_PIP, 10, "Running pip install omnivoice...")
                    try:
                        proc = subprocess.run(
                            pip_args,
                            capture_output=True,
                            text=True,
                            timeout=900,
                        )
                    except subprocess.TimeoutExpired:
                        raise RuntimeError("pip install timed out (15 min)")
                    if proc.returncode != 0:
                        stderr = (proc.stderr or "").strip()
                        err_lines = [ln for ln in stderr.splitlines() if ln.strip()]
                        err_msg = err_lines[-1] if err_lines else f"pip exit code {proc.returncode}"
                        raise RuntimeError(f"pip install failed: {err_msg}")
                    pip_done = True
                    self._align_torchvision_with_torch(on_progress, _report)
                    self._purge_tts_extension_modules()
                    continue
                raise RuntimeError(f"omnivoice import failed: {e}") from e

        if pip_done:
            _report(STATE_PIP, 100, "omnivoice installed successfully")
        else:
            _report(STATE_PIP, 100, "omnivoice already installed")

        if self._cancel:
            return

        if not self._ensure_torchcodec(on_progress, _report):
            raise RuntimeError(
                "torchcodec is required for TorchAudio to load WAV files (voice cloning). "
                "pip install torchcodec failed — check the log."
            )

        _report(STATE_MODEL, 0, "Preparing OmniVoice model...")

        numpy_repairs_model = 0
        max_numpy_repairs_model = 2
        torchcodec_repairs_model = 0
        max_torchcodec_repairs_model = 2
        while True:
            try:
                self._download_and_verify_omnivoice(on_progress, _report)
                break
            except Exception as e:
                if torchcodec_repairs_model < max_torchcodec_repairs_model and _is_torchcodec_missing_error(e):
                    torchcodec_repairs_model += 1
                    logger.warning(
                        "OmniVoice model step: torchcodec repair (%d): %s",
                        torchcodec_repairs_model,
                        e,
                    )
                    if self._ensure_torchcodec(on_progress, _report):
                        continue
                if numpy_repairs_model < max_numpy_repairs_model and _is_numpy_abi_error(e):
                    numpy_repairs_model += 1
                    logger.warning(
                        "OmniVoice install: numpy ABI on model load (repair %d): %s",
                        numpy_repairs_model,
                        e,
                    )
                    if not self._repair_numpy_abi(numpy_repairs_model, on_progress, _report):
                        raise RuntimeError(f"OmniVoice model load failed after NumPy repair: {e}") from e
                    try:
                        self._verify_omnivoice_import(on_progress, _report)
                    except Exception as e2:
                        raise RuntimeError(f"After NumPy repair, omnivoice import failed: {e2}") from e2
                    continue
                raise RuntimeError(f"OmniVoice model download/load failed: {e}") from e

        _report(STATE_MODEL, 100, "OmniVoice verified.")
        _report(STATE_DONE, 100, "OmniVoice installation complete.")
        if sys.platform == "win32":
            logger.info(
                "OmniVoice (Windows): TorchCodec may require FFmpeg *shared* DLLs (avutil/avcodec). "
                "PerkySue adds Python/ and Data/Tools/ffmpeg-shared/bin/ to the DLL search path. "
                "Copy bin/*.dll from e.g. BtbN ffmpeg-*-win64-gpl-shared into one of those folders, "
                "or run install_ffmpeg_shared_windows.bat in the portable root for instructions. "
                "pip install ffmpeg-python does not ship those DLLs."
            )

    def install_pytorch_cuda(
        self,
        index_url: str,
        on_progress: Optional[Callable[[str, int, str], None]] = None,
        on_done: Optional[Callable[[bool, str], None]] = None,
    ):
        """Replace CPU-only PyTorch with a CUDA wheel (large download). Background thread."""
        if self.is_running:
            logger.warning("TTS install already in progress")
            if on_done:
                on_done(False, "Another installation is already running.")
            return
        if not (index_url or "").strip().startswith("https://download.pytorch.org/whl/cu"):
            if on_done:
                on_done(False, "Invalid PyTorch index URL.")
            return

        self._cancel = False

        def _run():
            try:
                self._install_pytorch_cuda_impl(index_url.strip(), on_progress)
                if on_done:
                    on_done(True, "")
            except Exception as e:
                logger.error("PyTorch CUDA install failed: %s", e)
                self.state = STATE_ERROR
                if on_progress:
                    on_progress(STATE_ERROR, 0, str(e))
                if on_done:
                    on_done(False, str(e))

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def _install_pytorch_cuda_impl(
        self,
        index_url: str,
        on_progress: Optional[Callable[[str, int, str], None]] = None,
    ):
        def _report(state: str, pct: int, msg: str):
            self.state = state
            if on_progress:
                on_progress(state, pct, msg)
            logger.info("PyTorch CUDA [%s %d%%]: %s", state, pct, msg)

        idx_hint = "CUDA 12.8 / Blackwell" if "cu128" in index_url else "CUDA 12.4"
        _report(
            STATE_PYTORCH_CUDA,
            5,
            f"Installing PyTorch with {idx_hint} wheels (large download, several minutes)...",
        )

        if self._cancel:
            return

        args = [
            "--upgrade",
            "torch",
            "torchvision",
            "torchaudio",
            "--index-url",
            index_url,
        ]
        ok, tail = self._run_pip(args, timeout=2400)
        if not ok:
            raise RuntimeError((tail or "pip failed")[-1500:])

        # Never purge/re-import torch in this process. Pip upgrades on disk while the
        # interpreter still holds the old extension — reloading breaks torch/einops and TTS.
        _report(STATE_PYTORCH_CUDA, 90, "Verifying install (separate process)...")
        try:
            proc = subprocess.run(
                [
                    self.python_exe,
                    "-c",
                    "import torch; print(torch.__version__); "
                    "print('cuda_built', torch.backends.cuda.is_built()); "
                    "print('cuda_available', torch.cuda.is_available())",
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            out = ((proc.stdout or "") + (proc.stderr or "")).strip()
            if proc.returncode == 0 and out:
                logger.info("PyTorch after CUDA pip (fresh interpreter): %s", out[:500])
            elif proc.returncode != 0:
                logger.warning(
                    "PyTorch subprocess verify failed (rc=%s): %s",
                    proc.returncode,
                    out[:500] or "(no output)",
                )
        except Exception as ex:
            logger.debug("PyTorch subprocess verify skipped: %s", ex)

        _report(
            STATE_PYTORCH_CUDA,
            100,
            "Install complete — quit and restart PerkySue to load the new PyTorch.",
        )

        self.state = STATE_DONE

    @staticmethod
    def detect_python_exe() -> str:
        """Find the Python executable for pip commands.

        In portable PerkySue: Python/python.exe
        In dev: sys.executable
        """
        app_dir = Path(__file__).resolve().parent.parent.parent
        root_dir = app_dir.parent
        portable = root_dir / "Python" / "python.exe"
        if portable.exists():
            return str(portable)

        portable_mac = root_dir / "Python" / "bin" / "python3"
        if portable_mac.exists():
            return str(portable_mac)

        return sys.executable
