"""
Rules for accepting Data/Configs/license.json as Stripe Pro (shared by Orchestrator + diagnose_license CLI).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from utils.install_id import get_or_create_install_id


def evaluate_stripe_license_file(
    data: dict,
    configs_dir: Path,
) -> Tuple[Optional[Dict[str, Any]], Optional[str], bool]:
    """Same contract as Orchestrator._stripe_license_evaluate (see orchestrator docstring).

    Returns:
        (accepted_dict_or_none, reject_reason_or_none, signed_ok_for_marker).
    """
    if not isinstance(data, dict):
        return None, "license_json_not_object", False
    tier = (data.get("tier") or "pro").strip().lower()
    if tier in ("trialing", "trial"):
        tier = "pro"
    if tier != "pro":
        return None, f"root_tier_not_pro:{tier!r}", False

    # Trial cache can also use tier=pro for local gating UX, but it must never
    # be considered a paid Stripe proof for Plan Management ("Manage", renew date).
    source = (data.get("source") or "").strip().lower()
    if source == "trial":
        return None, "root_source_is_trial_not_stripe", False

    cur = get_or_create_install_id(Path(configs_dir)).strip()
    fid = data.get("install_id")
    if not isinstance(fid, str) or not fid.strip():
        return None, "root_install_id_missing_or_invalid", False
    if fid.strip() != cur:
        return None, "root_install_id_mismatch_vs_Data_Configs_install.id", False
    sid = data.get("subscription_id")
    stripe_sub_linked = isinstance(sid, str) and sid.strip().startswith("sub_")

    # Accept paid Stripe proof only when we have a Stripe subscription id.
    # This keeps legacy paid files compatible while excluding trial snapshots.
    if not stripe_sub_linked:
        return None, "subscription_id_missing_or_not_stripe_sub", False

    marker = Path(configs_dir) / "stripe_license_signed_once.marker"
    try:
        from utils.license_signature import verify_stripe_license_signature

        st, detail = verify_stripe_license_signature(data, cur)
        if st == "invalid":
            return None, f"signature_invalid:{detail or 'unknown'}", False
        if st == "ok":
            return data, None, True
        if st == "legacy" and stripe_sub_linked and marker.exists():
            return None, "legacy_sub_rejected_signed_marker_present", False
    except Exception as e:
        return None, f"verify_exception:{e!r}", False
    return data, None, False
