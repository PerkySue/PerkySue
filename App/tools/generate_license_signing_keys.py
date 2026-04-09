#!/usr/bin/env python3
"""
Generate ONE Ed25519 key pair for PerkySue license signing.

- Private PEM → Wrangler secret LICENSE_SIGNING_PRIVATE_KEY (never commit, never share).
- Public PEM  → paste into App/utils/license_signature.py as LICENSE_PUBLIC_KEY_PEM.

Run this **once per environment** (or when you deliberately rotate keys). Do **not** run it
again “to fix” bad_signature: that creates a *new* pair and makes the old Worker secret
and app pub disagree. To fix mismatch, either use the public key from the **same** private
file you uploaded to Wrangler, or upload a **new** private from a **new** run of this
script **and** update the app’s public key — then users need an online /check refresh.

Usage (embedded Python with cryptography installed):
  cd "C:\\path\\to\\PerkySue"
  Python\\python.exe App\\tools\\generate_license_signing_keys.py

Optional output directory:
  Python\\python.exe App\\tools\\generate_license_signing_keys.py --out C:\\secure\\keys
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Ed25519 pair for license signing.")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Directory for .pem files (default: current working directory)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing .pem files",
    )
    args = parser.parse_args()
    out_dir = (args.out or Path.cwd()).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    priv_name = "perkysue_license_ed25519_PRIVATE.pem"
    pub_name = "perkysue_license_ed25519_PUBLIC.pem"
    priv_path = out_dir / priv_name
    pub_path = out_dir / pub_name

    if not args.force and (priv_path.exists() or pub_path.exists()):
        print("Refusing to overwrite existing files. Use --force or choose another --out.", file=sys.stderr)
        print(f"  {priv_path}\n  {pub_path}", file=sys.stderr)
        return 1

    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization
    except ImportError:
        print("Missing package: cryptography. Use the same Python as PerkySue (after install.bat).", file=sys.stderr)
        return 1

    key = Ed25519PrivateKey.generate()
    priv_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    priv_path.write_bytes(priv_pem)
    pub_path.write_bytes(pub_pem)

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print()
    print("=== PerkySue license signing keys (Ed25519) ===")
    print(f"Generated at: {ts}")
    print()
    print(f"PRIVATE (secret): {priv_path}")
    print(f"PUBLIC  (embed):  {pub_path}")
    print()
    print("--- Next steps (do in order) ---")
    print()
    print("1) Worker - upload the PRIVATE file to Wrangler (once):")
    print("   Git Bash / cmd:")
    print(f'     wrangler secret put LICENSE_SIGNING_PRIVATE_KEY < "{priv_path}"')
    print("   PowerShell:")
    print(f'     Get-Content -Raw "{priv_path}" | wrangler secret put LICENSE_SIGNING_PRIVATE_KEY')
    print()
    print("2) App - open the PUBLIC file and copy the whole PEM block into:")
    print("     App/utils/license_signature.py -> LICENSE_PUBLIC_KEY_PEM")
    print()
    print("3) Deploy Worker + ship updated App/ folder.")
    print()
    print("4) Online refresh: launch app or GET /check so license.json gets a new signature.")
    print()
    print("--- PUBLIC PEM (for quick copy) ---")
    print(pub_pem.decode("ascii").rstrip())
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
