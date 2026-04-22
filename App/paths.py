"""
Portable path resolution for PerkySue.

Architecture:
    PerkySue/
    ├── App/                 ← SYSTEM (replaced on update)
    │   ├── configs/
    │   │   ├── defaults.yaml  ← Factory default settings
    │   │   └── modes.yaml     ← System mode definitions
    │   ├── sounds/            ← Audio feedback files
    │   └── ...source code
    │
    ├── Data/                ← USER (never touched by updates)
    │   ├── Configs/
    │   │   ├── config.yaml      ← User preferences (overrides defaults)
    │   │   └── custom_modes.yaml ← User-created modes (additive)
    │   ├── Models/            ← Downloaded models
    │   ├── HuggingFace/       ← HF cache
    │   ├── Logs/
    │   └── Cache/
    │
    ├── Python/              ← RUNTIME (updated independently)
    └── start.bat, install.bat, *.md, LICENSE, …

Update process: Overwrite App/ and selected portable-root files (*.bat, *.md, LICENSE).
    Data/ and Python/ are not modified by the in-app updater.
"""

import os
import sys
from pathlib import Path


class Paths:
    """Centralized path manager for the portable installation."""

    def __init__(self, data_dir: str = None):
        """
        Args:
            data_dir: Path to Data/ folder.
                      If None, auto-detect:
                      1. PERKYSUE_DATA env var
                      2. ../Data/ relative to App/
                      3. ./Data/ relative to CWD
        """
        if data_dir:
            self._data = Path(data_dir)
        elif os.environ.get("PERKYSUE_DATA"):
            self._data = Path(os.environ["PERKYSUE_DATA"])
        else:
            app_dir = Path(__file__).resolve().parent
            root_dir = app_dir.parent
            candidate = root_dir / "Data"
            if candidate.exists():
                self._data = candidate
            else:
                self._data = Path.cwd() / "Data"

        self._app = Path(__file__).resolve().parent

        # Create missing directories
        self._ensure_dirs()

    def _ensure_dirs(self):
        """Create directories if they don't exist."""
        for d in [
            self.data, self.models, self.models_whisper, self.models_llm,
            self.models_tts, self.huggingface, self.configs, self.logs,
            self.audio, self.cache, self.native, self.plugins,
        ]:
            d.mkdir(parents=True, exist_ok=True)

    # ─── Data directories (USER — persistent across updates) ───

    @property
    def data(self) -> Path:
        return self._data

    @property
    def models(self) -> Path:
        return self._data / "Models"

    @property
    def models_whisper(self) -> Path:
        return self._data / "Models" / "Whisper"

    @property
    def models_llm(self) -> Path:
        return self._data / "Models" / "LLM"

    @property
    def models_tts(self) -> Path:
        return self._data / "Models" / "TTS"

    @property
    def huggingface(self) -> Path:
        return self._data / "HuggingFace"

    @property
    def configs(self) -> Path:
        return self._data / "Configs"

    @property
    def logs(self) -> Path:
        return self._data / "Logs"

    @property
    def audio(self) -> Path:
        return self._data / "Audio"

    @property
    def cache(self) -> Path:
        return self._data / "Cache"

    @property
    def native(self) -> Path:
        return self._data / "Native"

    @property
    def plugins(self) -> Path:
        """Runtime extensions under ``Data/Plugins/<id>/`` (survive App/ updates).

        First-party examples (``dev``, ``avatar_editor``) ship templates outside the
        Apache tree; **third-party or proprietary** code should also live here only,
        loaded via ``utils.plugin_host`` — see that module's docstring for the SPI.
        """
        return self._data / "Plugins"

    # ─── User config files (in Data/ — persist across updates) ───

    @property
    def user_config_file(self) -> Path:
        """User preferences (overrides system defaults)."""
        return self.configs / "config.yaml"

    @property
    def custom_modes_file(self) -> Path:
        """User-created custom modes (additive to system modes)."""
        return self.configs / "custom_modes.yaml"

    # ─── System config files (in App/ — replaced on update) ───

    @property
    def app_dir(self) -> Path:
        return self._app

    @property
    def defaults_file(self) -> Path:
        """Factory default settings."""
        return self._app / "configs" / "defaults.yaml"

    @property
    def modes_file(self) -> Path:
        """System mode definitions."""
        return self._app / "configs" / "modes.yaml"

    @property
    def voice_modes_file(self) -> Path:
        """System voice (TTS payload) overlays for LLM modes."""
        return self._app / "configs" / "voice_modes.yaml"

    @property
    def user_voice_modes_file(self) -> Path:
        """User overrides for voice mode overlays (merged over system)."""
        return self.configs / "voice_modes.yaml"

    # ─── Legacy aliases (for backward compat) ───

    @property
    def config_file(self) -> Path:
        """Alias → user_config_file."""
        return self.user_config_file

    # ─── Other files ───

    @property
    def db_file(self) -> Path:
        return self._data / "perkysue.db"

    @property
    def log_file(self) -> Path:
        return self.logs / "perkysue.log"

    @property
    def root(self) -> Path:
        return self._data.parent

    @property
    def python_dir(self) -> Path:
        return self.root / "Python"

    def set_env(self):
        """Set environment variables to keep all downloads portable.

        huggingface_hub reads ``HF_HUB_CACHE`` / legacy ``HUGGINGFACE_HUB_CACHE`` at import time;
        setting them here (and passing explicit ``cache_dir`` where libraries allow) keeps the
        Hub layout under ``Data/HuggingFace/hub/`` instead of ``%USERPROFILE%\\.cache\\huggingface``.
        """
        hf = str(self.huggingface.resolve())
        hub = str((self.huggingface / "hub").resolve())
        self.huggingface.mkdir(parents=True, exist_ok=True)
        os.environ["HF_HOME"] = hf
        os.environ["HF_HUB_CACHE"] = hub
        os.environ["HUGGINGFACE_HUB_CACHE"] = hub
        os.environ["TRANSFORMERS_CACHE"] = hf
        os.environ["XDG_CACHE_HOME"] = str(self.cache.resolve())
        os.environ["PERKYSUE_DATA"] = str(self._data)

    def summary(self) -> str:
        """Diagnostic summary of all paths."""
        lines = [
            f"  Data:         {self.data}",
            f"  Models:       {self.models}",
            f"    Whisper:    {self.models_whisper}",
            f"    LLM:        {self.models_llm}",
            f"    TTS:        {self.models_tts}",
            f"  HuggingFace:  {self.huggingface}",
            f"  User config:  {self.user_config_file}",
            f"  Sys defaults: {self.defaults_file}",
            f"  Sys modes:    {self.modes_file}",
            f"  Custom modes: {self.custom_modes_file}",
            f"  Logs:         {self.logs}",
        ]
        return "\n".join(lines)


# ─── Global singleton ───
_instance: Paths = None


def get_paths(data_dir: str = None) -> Paths:
    """Return the global Paths instance (create if needed)."""
    global _instance
    if _instance is None:
        _instance = Paths(data_dir=data_dir)
    return _instance
