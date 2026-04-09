"""
Installation UUID for licensing (Worker / Stripe / KV).

`Data/Configs/install.id` holds a single UUID (plain text, one line).
It identifies this portable PerkySue folder — not a web user account.
Generated on the machine; perkysue.com does not issue it in the normal flow.
"""

from __future__ import annotations

import uuid
from pathlib import Path

INSTALL_ID_FILENAME = "install.id"


def get_or_create_install_id(configs_dir: Path) -> str:
    """
    Return the install_id. Creates `install.id` on first run (missing or empty file).

    Never overwrites a non-empty file — preserves identity across backups.
    """
    configs_dir = Path(configs_dir)
    configs_dir.mkdir(parents=True, exist_ok=True)
    path = configs_dir / INSTALL_ID_FILENAME
    if path.is_file():
        raw = path.read_text(encoding="utf-8").strip()
        if raw:
            return raw
    new_id = str(uuid.uuid4())
    path.write_text(new_id + "\n", encoding="utf-8")
    return new_id
