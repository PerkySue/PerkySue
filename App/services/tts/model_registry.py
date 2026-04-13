"""
Deterministic TTS model registry.

Keeps a product-facing manifest under Data/Models/TTS so engine loading is
stable across restarts and independent from implicit HF cache behavior.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

logger = logging.getLogger("perkysue.tts.registry")


@dataclass
class EngineSpec:
    engine_id: str
    repo_id: str
    revision: str
    allow_patterns: List[str]


class TTSModelRegistry:
    def __init__(self, paths: Any, models_tts_dir: Path, hf_cache_dir: Path, app_version: str):
        self.paths = paths
        self.models_tts_dir = Path(models_tts_dir)
        self.hf_cache_dir = Path(hf_cache_dir)
        self.app_version = str(app_version or "")
        self.registry_file = self.models_tts_dir / "registry.json"
        self.spec_file = Path(self.paths.app_dir) / "configs" / "model_registry.yaml"

    def _load_json(self) -> Dict[str, Any]:
        if not self.registry_file.is_file():
            return {"schema_version": 1, "engines": {}}
        try:
            data = json.loads(self.registry_file.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return {"schema_version": 1, "engines": {}}
            data.setdefault("schema_version", 1)
            data.setdefault("engines", {})
            if not isinstance(data["engines"], dict):
                data["engines"] = {}
            return data
        except Exception as e:
            logger.warning("TTS registry: failed to read %s: %s", self.registry_file, e)
            return {"schema_version": 1, "engines": {}}

    def _save_json(self, data: Dict[str, Any]) -> None:
        self.models_tts_dir.mkdir(parents=True, exist_ok=True)
        self.registry_file.write_text(
            json.dumps(data, ensure_ascii=True, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def _load_spec(self) -> Dict[str, Any]:
        if not self.spec_file.is_file():
            return {}
        try:
            obj = yaml.safe_load(self.spec_file.read_text(encoding="utf-8")) or {}
            return obj if isinstance(obj, dict) else {}
        except Exception as e:
            logger.warning("TTS registry: failed to read spec %s: %s", self.spec_file, e)
            return {}

    def get_engine_spec(self, engine_id: str, fallback_repo: Optional[str] = None) -> Optional[EngineSpec]:
        spec = self._load_spec()
        engines = spec.get("tts_engines") if isinstance(spec, dict) else None
        row = engines.get(engine_id) if isinstance(engines, dict) else None
        repo_id = ""
        revision = ""
        allow_patterns: List[str] = []
        if isinstance(row, dict):
            repo_id = str(row.get("repo_id") or "").strip()
            revision = str(row.get("revision") or "").strip()
            if isinstance(row.get("allow_patterns"), list):
                allow_patterns = [str(x) for x in row.get("allow_patterns") if str(x).strip()]
        if not repo_id:
            repo_id = str(fallback_repo or "").strip()
        if not repo_id:
            return None
        if not revision:
            revision = "main"
        if not allow_patterns:
            allow_patterns = ["*"]
        return EngineSpec(engine_id=engine_id, repo_id=repo_id, revision=revision, allow_patterns=allow_patterns)

    def get_entry(self, engine_id: str) -> Optional[Dict[str, Any]]:
        data = self._load_json()
        e = data.get("engines", {}).get(engine_id)
        return e if isinstance(e, dict) else None

    def set_entry(
        self,
        engine_id: str,
        repo_id: str,
        revision: str,
        snapshot_path: Path,
        files: List[str],
        reason: str,
    ) -> None:
        data = self._load_json()
        engines = data.setdefault("engines", {})
        engines[engine_id] = {
            "engine_id": engine_id,
            "repo_id": repo_id,
            "revision": revision,
            "resolved_snapshot": str(snapshot_path),
            "files": sorted(files),
            "installed_at": datetime.now(timezone.utc).isoformat(),
            "app_version": self.app_version,
            "reason": reason,
        }
        self._save_json(data)

    def validate_entry(self, engine_id: str) -> Tuple[bool, str]:
        e = self.get_entry(engine_id)
        if not e:
            return False, "no_manifest"
        snap = Path(str(e.get("resolved_snapshot") or ""))
        if not snap.is_dir():
            return False, "missing_snapshot"
        files = e.get("files")
        if not isinstance(files, list) or not files:
            return False, "missing_files_list"
        for rel in files:
            if not (snap / str(rel)).is_file():
                return False, "missing_file"
        return True, "ok"

    def resolve_local_snapshot(
        self,
        engine_id: str,
        fallback_repo: Optional[str] = None,
        local_files_only: bool = True,
    ) -> Tuple[Optional[Path], str]:
        spec = self.get_engine_spec(engine_id, fallback_repo=fallback_repo)
        if spec is None:
            return None, "no_engine_spec"
        try:
            from huggingface_hub import snapshot_download

            local_path = Path(
                snapshot_download(
                    repo_id=spec.repo_id,
                    revision=spec.revision,
                    allow_patterns=spec.allow_patterns,
                    cache_dir=str((self.hf_cache_dir / "hub").resolve()),
                    local_files_only=local_files_only,
                )
            )
            return local_path, "ok"
        except Exception:
            return None, "snapshot_unavailable"

    def refresh_from_cache(
        self,
        engine_id: str,
        fallback_repo: Optional[str] = None,
        reason: str = "refresh",
        local_files_only: bool = True,
    ) -> Tuple[bool, str]:
        spec = self.get_engine_spec(engine_id, fallback_repo=fallback_repo)
        if spec is None:
            return False, "no_engine_spec"
        snap, status = self.resolve_local_snapshot(
            engine_id=engine_id,
            fallback_repo=fallback_repo,
            local_files_only=local_files_only,
        )
        if snap is None:
            return False, status
        files = [str(p.relative_to(snap)) for p in snap.rglob("*") if p.is_file()]
        if not files:
            return False, "snapshot_empty"
        self.set_entry(
            engine_id=engine_id,
            repo_id=spec.repo_id,
            revision=spec.revision,
            snapshot_path=snap,
            files=files,
            reason=reason,
        )
        return True, "ok"

    def status(self) -> Dict[str, Any]:
        data = self._load_json()
        out: Dict[str, Any] = {"registry_file": str(self.registry_file), "engines": {}}
        for engine_id, entry in (data.get("engines") or {}).items():
            ok, reason = self.validate_entry(engine_id)
            out["engines"][engine_id] = {
                "valid": bool(ok),
                "reason": reason,
                "repo_id": entry.get("repo_id"),
                "revision": entry.get("revision"),
                "resolved_snapshot": entry.get("resolved_snapshot"),
            }
        return out
