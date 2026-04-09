#!/usr/bin/env python3
"""Print why Stripe Pro may not apply (license.json vs install.id vs signature vs dev UI preview).

Does not import the full Orchestrator (avoids numpy / STT stack). Use the same Python as the app.

Examples:
  cd App
  python diagnose_license.py

  set PERKYSUE_DATA=C:\\path\\to\\Data
  python diagnose_license.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from paths import Paths
from utils.install_id import get_or_create_install_id
from utils.stripe_license_file import evaluate_stripe_license_file


def _load_dev_plugin(paths):
    """Try to load extension module. Returns module or None."""
    try:
        import importlib.util
        init_py = paths.plugins / "dev" / "__init__.py"
        if not init_py.is_file():
            return None
        spec = importlib.util.spec_from_file_location("perkysue_dev_plugin", init_py)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


def _user_plan_preview(configs: Path) -> str:
    try:
        import yaml
    except ImportError:
        return ""
    p = configs / "config.yaml"
    if not p.is_file():
        return ""
    try:
        cfg = yaml.safe_load(p.read_text(encoding="utf-8", errors="replace")) or {}
        return str(cfg.get("plan") or "").strip().lower()
    except Exception:
        return ""


def _user_plan_preview_dict(configs: Path) -> dict:
    """Return config dict (or empty) for the extension module API."""
    try:
        import yaml
    except ImportError:
        return {}
    p = configs / "config.yaml"
    if not p.is_file():
        return {}
    try:
        cfg = yaml.safe_load(p.read_text(encoding="utf-8", errors="replace")) or {}
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


def main() -> None:
    paths = Paths()
    cfg_dir = paths.configs
    dev = _load_dev_plugin(paths)

    print("--- PerkySue license gate (lightweight) ---")
    if dev is not None:
        try:
            dev_lines = dev.collect_diagnostics(
                _user_plan_preview_dict(cfg_dir), paths.plugins
            )
            for line in dev_lines:
                print(line)
        except Exception as e:
            print(f"extension module present but collect_diagnostics() failed: {e}")
    else:
        print("extension module: not installed (production mode)")

    lic = cfg_dir / "license.json"
    if not lic.is_file():
        print("license.json: missing")
        print()
        print(f"Data dir: {paths.data}")
        return

    try:
        data = json.loads(lic.read_text(encoding="utf-8", errors="ignore").strip() or "{}")
    except json.JSONDecodeError as e:
        print(f"license.json: invalid JSON ({e})")
        print()
        print(f"Data dir: {paths.data}")
        return

    if not isinstance(data, dict):
        print("license.json: root is not a JSON object")
        print()
        print(f"Data dir: {paths.data}")
        return

    ok, reason, _signed = evaluate_stripe_license_file(data, cfg_dir)
    if ok is None:
        print(f"stripe_license_eval: REJECTED — {reason}")
        if str(reason).startswith("signature_invalid:bad_signature"):
            print()
            print("--- English ---")
            print("bad_signature: public key in App/utils/license_signature.py does not match")
            print("the private key Cloudflare uses for LICENSE_SIGNING_PRIVATE_KEY.")
            print()
            print("--- Francais ---")
            print("Si tu as modifie license.json HORS LIGNE (ex. dates) : c'est NORMAL que la")
            print("  signature ne colle plus ; remets internet et laisse l'app rafraichir.")
            print("Si tu n'as RIEN modifie : voir cle publique app vs Worker (ci-dessous).")
            print()
            print("Pourquoi le relink e-mail ne suffit pas quand c'est un probleme de cle :")
            print("On sait deja tout ce que la math permet de savoir :")
            print("  - Le fichier license.json contient une signature faite par le Worker.")
            print("  - Cette signature ne correspond PAS a la cle PUBLIQUE dans CE dossier App.")
            print("Donc : cle privee sur Cloudflare et cle publique dans l'app ne sont PAS la meme paire.")
            print()
            print("Ni ce script, ni l'assistant IA, ne peuvent lire le secret Wrangler : on ne peut pas")
            print("deviner si tu as perdu le .pem, colle la mauvaise pub, ou regenere des cles melangees.")
            print("Relier l'abonnement (email / install_id) ne change pas les cles : l'erreur reste.")
            print()
            print("--- UNE seule procedure qui marche (remplacer la paire entiere) ---")
            print("  1) Depuis la racine PerkySue, une seule fois :")
            print('     Python\\python.exe App\\tools\\generate_license_signing_keys.py --out C:\\chemin\\SECURISE')
            print("  2) Wrangler : mettre le fichier *_PRIVATE.pem dans le secret LICENSE_SIGNING_PRIVATE_KEY")
            print("     (PowerShell: Get-Content -Raw ...PRIVATE.pem | wrangler secret put LICENSE_SIGNING_PRIVATE_KEY)")
            print("  3) Copier le bloc ENTIER du fichier *_PUBLIC.pem dans license_signature.py -> LICENSE_PUBLIC_KEY_PEM")
            print("  4) wrangler deploy + remplacer le dossier App/ cote utilisateur")
            print("  5) Lancer l'app en ligne pour rafraichir license.json")
    else:
        print("stripe_license_eval: accepted (signature + root fields OK for Pro)")

    cur = get_or_create_install_id(cfg_dir).strip()
    print()
    print(f"Data dir: {paths.data}")
    print(f"install.id (this folder): {cur!r}")
    lj = data.get("install_id")
    if isinstance(lj, str) and lj.strip():
        print(f"license.json install_id: {lj.strip()!r}")
        if lj.strip() != cur:
            print("  → mismatch blocks Pro until you re-link or restore install.id")


if __name__ == "__main__":
    main()
