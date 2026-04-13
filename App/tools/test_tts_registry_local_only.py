#!/usr/bin/env python3
"""
Basic non-regression checks for deterministic TTS registry behavior.

This is a lightweight runtime check (no pytest dependency).
"""

from __future__ import annotations

import argparse
import json

from paths import get_paths
from services.tts.model_registry import TTSModelRegistry


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate TTS registry local-only behavior")
    parser.add_argument("--data", "-d", help="Path to Data folder")
    args = parser.parse_args()

    paths = get_paths(data_dir=args.data)
    paths.set_env()
    reg = TTSModelRegistry(
        paths=paths,
        models_tts_dir=paths.models_tts,
        hf_cache_dir=paths.huggingface,
        app_version="",
    )

    status = reg.status()
    _assert(isinstance(status, dict), "status must be dict")
    _assert("engines" in status, "status.engines missing")

    # Local-only resolution should never force network.
    for engine_id, fallback in (("chatterbox", "ResembleAI/chatterbox"), ("omnivoice", "k2-fsa/OmniVoice")):
        _, reason = reg.resolve_local_snapshot(engine_id=engine_id, fallback_repo=fallback, local_files_only=True)
        _assert(reason in ("ok", "snapshot_unavailable", "no_engine_spec"), f"unexpected reason for {engine_id}: {reason}")

    print(json.dumps({"ok": True, "status": status}, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
