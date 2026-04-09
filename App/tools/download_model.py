"""
PerkySue — Model Downloader
Downloads GGUF models into Data/Models/LLM/
Uses App/configs/recommended_models.yaml as single source of truth (GUI + console).
"""
import os
import sys
from pathlib import Path

# Add App/ to path so "from paths import get_paths" and config load work
APP_ROOT = Path(__file__).resolve().parent.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

# Path to recommended models catalog (used by GUI and this script)
RECOMMENDED_MODELS_YAML = APP_ROOT / "configs" / "recommended_models.yaml"


def load_recommended_models():
    """Load catalog from YAML. Returns list of model dicts; empty list on error."""
    if not RECOMMENDED_MODELS_YAML.exists():
        return []
    try:
        import yaml
        with open(RECOMMENDED_MODELS_YAML, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "models" in data:
            return data["models"]
        return []
    except Exception:
        return []


def _catalog_entry_description(m: dict) -> str:
    """Console menu line: optional description field, else first available localized comment (US → GB → legacy)."""
    if not isinstance(m, dict):
        return ""
    d = (m.get("description") or "").strip()
    if d:
        return d
    for key in ("comment_us", "comment_gb", "comment"):
        v = m.get(key)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def main():
    # Resolve paths
    from paths import get_paths
    data_dir = os.environ.get("PERKYSUE_DATA")
    paths = get_paths(data_dir=data_dir)
    models_dir = str(paths.models_llm)

    # Ensure LLM dir exists
    os.makedirs(models_dir, exist_ok=True)

    # Show existing models
    existing = [f for f in os.listdir(models_dir) if f.endswith(".gguf")]
    if existing:
        print()
        print("  Existing models in Data\\Models\\LLM\\:")
        for f in existing:
            size_mb = os.path.getsize(os.path.join(models_dir, f)) / 1024 / 1024
            print(f"    - {f}  ({size_mb:.0f} MB)")

    catalog = load_recommended_models()

    print()
    print("  =============================================")
    print("  PerkySue - Model Downloader")
    print("  =============================================")
    print()
    print("  Recommended models (from configs/recommended_models.yaml):")
    print()

    if not catalog:
        print("  [WARNING] No catalog found. Add entries to App/configs/recommended_models.yaml")
        print("  Fallback: custom download only.")
        print()
        print("  [5] Custom HuggingFace download")
        print("  [0] Cancel")
        print()
        choice = input("  Your choice: ").strip()
        if choice == "0":
            print("  Cancelled.")
            return
        if choice != "5":
            print("  Invalid choice.")
            return
        repo = input("  HuggingFace repo (e.g. Qwen/Qwen2.5-7B-Instruct-GGUF): ").strip()
        filename = input("  Filename (e.g. model-q4_k_m.gguf): ").strip()
        if not repo or not filename:
            print("  Invalid input.")
            return
        repo_id, filename = repo, filename
    else:
        for i, m in enumerate(catalog, 1):
            name = m.get("name", "?")
            params = m.get("params", "")
            size_hint = m.get("size_hint", "")
            desc = _catalog_entry_description(m)
            line = f"  [{i}] {name}  {params}  {size_hint}"
            if desc:
                line += f"  - {desc}"
            print(line)
        print("  [5] Custom HuggingFace download")
        print("  [0] Cancel")
        print()

        choice = input("  Your choice [1]: ").strip() or "1"

        if choice == "0":
            print("  Cancelled.")
            return

        if choice == "5":
            repo = input("  HuggingFace repo (e.g. Qwen/Qwen2.5-7B-Instruct-GGUF): ").strip()
            filename = input("  Filename (e.g. model-q4_k_m.gguf): ").strip()
            if not repo or not filename:
                print("  Invalid input.")
                return
            repo_id, filename = repo, filename
        else:
            try:
                idx = int(choice)
                if 1 <= idx <= len(catalog):
                    entry = catalog[idx - 1]
                    repo_id = entry["repo_id"]
                    filename = entry["filename"]
                else:
                    print("  Invalid choice.")
                    return
            except ValueError:
                print("  Invalid choice.")
                return

    print()
    print(f"  Downloading {filename}")
    print(f"  From: huggingface.co/{repo_id}")
    print(f"  To:   {models_dir}")
    print()
    print("  This may take several minutes...")
    print()

    try:
        from huggingface_hub import hf_hub_download
        path = hf_hub_download(
            repo_id=repo_id,
            filename=filename,
            local_dir=models_dir,
        )
        size_mb = os.path.getsize(path) / 1024 / 1024
        print()
        print(f"  Done! Model saved to:")
        print(f"  {path}")
        print(f"  Size: {size_mb:.0f} MB")
        print()
        print("  You can now run start.bat!")

    except Exception as e:
        print(f"  ERROR: {e}")
        print()
        print(f"  Manual download: https://huggingface.co/{repo_id}")
        print(f"  Place the .gguf file in: {models_dir}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n  ERROR: {e}")
        import traceback
        traceback.print_exc()
