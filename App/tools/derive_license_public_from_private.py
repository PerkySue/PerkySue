#!/usr/bin/env python3
"""
Derive the Ed25519 PUBLIC PEM from the same PRIVATE PEM you put in Wrangler
(LICENSE_SIGNING_PRIVATE_KEY). Paste the output into App/utils/license_signature.py
as LICENSE_PUBLIC_KEY_PEM.

Usage (paths with spaces need quotes):
  Python\\python.exe App\\tools\\derive_license_public_from_private.py C:\\Users\\Me\\Desktop\\ma_cle_privee.pem

Optional: also write to a file
  ...derive_license_public_from_private.py ma_cle_privee.pem --out pub.pem
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("private_pem", type=Path, help="Path to your BEGIN PRIVATE KEY ... PEM file")
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write public PEM to this file (optional)",
    )
    args = p.parse_args()
    path = args.private_pem
    if not path.is_file():
        print(f"File not found: {path}", file=sys.stderr)
        return 1
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
    except ImportError:
        print("Need package: cryptography (use PerkySue's Python after install.bat).", file=sys.stderr)
        return 1

    priv_bytes = path.read_bytes()
    key = load_pem_private_key(priv_bytes, password=None)
    pub_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    text = pub_pem.decode("ascii")
    if args.out:
        args.out.write_bytes(pub_pem)
        print(f"Wrote: {args.out.resolve()}")
    print()
    print("--- Copy everything below into license_signature.py -> LICENSE_PUBLIC_KEY_PEM ---")
    print(text.rstrip())
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
