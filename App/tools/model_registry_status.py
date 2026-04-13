#!/usr/bin/env python3
"""
Print deterministic TTS model registry status.
"""

from __future__ import annotations

import argparse
import json

from paths import get_paths
from services.tts.model_registry import TTSModelRegistry


def main() -> int:
    parser = argparse.ArgumentParser(description="Show TTS model registry status")
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
    print(json.dumps(reg.status(), ensure_ascii=True, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
