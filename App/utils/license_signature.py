"""
Ed25519 verification for GET /check license_payload + license_signature (Worker-signed).

Orchestrator may require a signed payload for sub_* only while
``stripe_license_signed_once.marker`` exists (see refresh_license_from_remote).

Replace LICENSE_PUBLIC_KEY_PEM with your deployment public key (matches Worker secret).

Troubleshooting ``bad_signature`` (Ed25519 verify failed on ``license_payload``):
  1. **Tampered file** — Any change to signed fields without a new server signature
     (common when editing ``license.json`` offline). **Fix:** go online; ``/check`` refresh.
  2. **Key mismatch** — ``LICENSE_PUBLIC_KEY_PEM`` in this build is not the public half of
     the Worker's ``LICENSE_SIGNING_PRIVATE_KEY``. Re-export pub from the same priv PEM.
  3. **Canonical JSON mismatch** — Worker signing bytes must match
     ``canonical_license_payload_bytes`` (sorted keys, compact separators, UTF-8).
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

# Ed25519 public key (PEM) — must match Worker secret LICENSE_SIGNING_PRIVATE_KEY pair.
# Regenerate for production: openssl genpkey -algorithm ED25519 -out priv.pem
#   openssl pkey -in priv.pem -pubout -out pub.pem
# Paste pub.pem body here; wrangler secret put LICENSE_SIGNING_PRIVATE_KEY < priv.pem
LICENSE_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAvGK09oLt6LD6Wqg4lG7VBEfzFa9t78srIeX97Z25iHY=
-----END PUBLIC KEY-----
"""

# Max wall-clock time without a fresh server-signed proof (discourages stale backups).
OFFLINE_MAX_DAYS = 30


def canonical_license_payload_bytes(payload: dict) -> bytes:
    """Must match Worker stableStringify (sorted keys, compact separators, UTF-8).

    Uses default ``ensure_ascii=True`` so non-ASCII matches ``JSON.stringify`` (\\uXXXX escapes).
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _parse_iso_utc(s: Any) -> Optional[datetime]:
    if not isinstance(s, str) or not s.strip():
        return None
    raw = s.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def verify_stripe_license_signature(
    data: Dict[str, Any],
    current_install_id: str,
) -> Tuple[str, Optional[str]]:
    """
    Returns (status, detail) where status is:
      'ok' — signature valid and time rules pass
      'legacy' — no license_signature / license_payload (old cache or Worker unsigned)
      'invalid' — signature present but wrong / expired / tampered
    """
    sig = data.get("license_signature")
    payload = data.get("license_payload")
    if sig is None and payload is None:
        return ("legacy", None)
    if sig is None or payload is None:
        return ("invalid", "missing_license_signature_or_payload")
    if not isinstance(payload, dict):
        return ("invalid", "license_payload_not_object")
    if not isinstance(sig, str) or not sig.strip():
        return ("invalid", "bad_signature_encoding")

    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError:
        return ("invalid", "cryptography_not_installed")

    try:
        pub = serialization.load_pem_public_key(
            LICENSE_PUBLIC_KEY_PEM.strip().encode("ascii"),
        )
        if not isinstance(pub, Ed25519PublicKey):
            return ("invalid", "wrong_key_type")
        msg = canonical_license_payload_bytes(payload)
        raw_sig = base64.b64decode(sig.strip(), validate=True)
        pub.verify(raw_sig, msg)
    except InvalidSignature:
        return ("invalid", "bad_signature")
    except Exception as e:
        return ("invalid", str(e))

    iid = (payload.get("install_id") or "").strip()
    if iid != (current_install_id or "").strip():
        return ("invalid", "install_id_mismatch")

    if payload.get("v") != 1:
        return ("invalid", "unsupported_payload_version")

    tier = (payload.get("tier") or "").strip().lower()
    if tier in ("trialing", "trial"):
        tier = "pro"
    if tier != "pro" or not payload.get("active"):
        return ("invalid", "payload_not_active_pro")

    exp_s = payload.get("expires_at")
    if exp_s is not None:
        exp_dt = _parse_iso_utc(exp_s)
        if exp_dt is not None and datetime.now(timezone.utc) > exp_dt:
            return ("invalid", "past_subscription_period_end")

    issued_s = payload.get("issued_at")
    issued_dt = _parse_iso_utc(issued_s)
    if issued_dt is None:
        return ("invalid", "missing_issued_at")
    deadline = issued_dt + timedelta(days=OFFLINE_MAX_DAYS)
    if datetime.now(timezone.utc) > deadline:
        return ("invalid", "offline_proof_too_old")

    return ("ok", None)
