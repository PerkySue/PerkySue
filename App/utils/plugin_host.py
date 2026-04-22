"""
Host-side plugin loading (SPI) — stable surface in the open-source tree.

Why this module exists
-----------------------
PerkySue (App + GUI) is distributed under Apache-2.0. Third parties who want
**proprietary** add-ons should ship Python (or other logic) **only** under
``Data/Plugins/<plugin_id>/``, loaded at runtime via ``importlib``, not merged
into the Apache-licensed repository.

This file defines the **small, reviewed contract** the OSS app exposes:
paths, safe package resolution, and a generic loader. Implementations
(proprietary or not) live beside user data and survive ``App/`` updates.

Licensing note (non-legal, practical)
--------------------------------------
- Code **committed inside** this repository is generally treated as
  contributed under the project license unless otherwise agreed.
- A **separate artifact** installed only on a user's machine under
  ``Data/Plugins/`` is not "the same work" as the GitHub tree; vendors often
  combine Apache OSS apps with closed plugins **provided** the boundary is
  clear. If a plugin **imports and subclasses** large parts of App code, you
  may need counsel on derivative-work questions in your jurisdiction.
- Stronger isolation (subprocess, HTTP service, separate .dll with C ABI)
  increases separation at the cost of complexity.

Plugin layout (recommended)
---------------------------
``Data/Plugins/<plugin_id>/``
    manifest.yaml          # optional; keys depend on the feature (see docs)
    __init__.py            # optional entry; or another .py via manifest
    ...                    # arbitrary proprietary modules

Optional manifest keys (convention, evolve as needed)::

    enabled: true
    entry: "main.py"      # if absent, ``__init__.py`` is tried first

Public API (orchestrator / GUI may call)
----------------------------------------
"""

from __future__ import annotations

import importlib.util
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("perkysue.plugin_host")

# Single-segment folder name under Data/Plugins/
_PLUGIN_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]{0,63}$")


def is_safe_plugin_id(plugin_id: str) -> bool:
    if not plugin_id or plugin_id.strip() != plugin_id:
        return False
    if ".." in plugin_id or "/" in plugin_id or "\\" in plugin_id:
        return False
    return bool(_PLUGIN_ID_RE.match(plugin_id))


def plugin_dir(plugins_root: Path, plugin_id: str) -> Optional[Path]:
    """Return ``plugins_root / plugin_id`` if ``plugin_id`` is safe, else None."""
    if not is_safe_plugin_id(plugin_id):
        logger.warning("Rejected unsafe plugin_id %r", plugin_id)
        return None
    return plugins_root / plugin_id


def load_plugin_module(
    plugins_root: Path,
    plugin_id: str,
    *,
    import_name: str,
    entry_filename: str = "__init__.py",
) -> Optional[ModuleType]:
    """
    Load ``Data/Plugins/<plugin_id>/<entry_filename>`` as a standalone module.

    Args:
        plugins_root: e.g. ``paths.plugins`` (``Data/Plugins``).
        plugin_id: subdirectory name (validated).
        import_name: unique ``spec_from_file_location`` name (avoid collisions).
        entry_filename: file to execute (default package ``__init__.py``).

    Returns:
        Loaded module, or ``None`` if missing / unsafe / error.
    """
    base = plugin_dir(plugins_root, plugin_id)
    if base is None:
        return None
    file_path = base / entry_filename
    if not file_path.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location(
            import_name,
            file_path,
            submodule_search_locations=[str(base)],
        )
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        # Register early so relative imports like ``from .engine import ...`` work
        # while the plugin package ``__init__`` executes.
        sys.modules[import_name] = mod
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        sys.modules.pop(import_name, None)
        logger.exception("Failed to load plugin %s from %s", plugin_id, file_path)
        return None


def list_plugin_ids(plugins_root: Path) -> list[str]:
    """Directory names under ``plugins_root`` (non-hidden, safe ids only)."""
    out: list[str] = []
    if not plugins_root.is_dir():
        return out
    try:
        for p in sorted(plugins_root.iterdir()):
            if not p.is_dir() or p.name.startswith("."):
                continue
            if is_safe_plugin_id(p.name):
                out.append(p.name)
    except OSError:
        pass
    return out


@dataclass
class PluginHostContext:
    """Narrow handle passed into optional ``register_plugin(ctx)`` hooks (future).

    Keep this object small and stable so proprietary code depends only on
    documented fields. Plugins should use ``logging.getLogger(__name__)`` for logs.
    """

    paths: Any
    get_orchestrator: Callable[[], Any]
    invoke_llm: Optional[Callable[..., str]] = None
    list_skins: Optional[Callable[[], list[dict[str, Any]]]] = None
    emit_progress: Optional[Callable[[dict[str, Any]], None]] = None
    is_effective_pro: Optional[Callable[[], bool]] = None
