"""The single audit helper every module uses."""

import sqlite3

from app.db import now_str

MODULES = ("kyc", "refunds", "flags", "auth")


def log_audit(
    db: sqlite3.Connection,
    actor: dict,
    module: str,
    entity_type: str,
    entity_id: int | None,
    action: str,
    before: str | None,
    after: str | None,
    comment: str | None = None,
) -> int:
    """Insert one audit entry. Does not commit: the caller commits it together
    with the change it describes, so the change and its audit row are atomic."""
    if module not in MODULES:
        raise ValueError(f"unknown audit module: {module}")
    cur = db.execute(
        "INSERT INTO audit_log (created_at, actor_email, actor_role, module, entity_type, entity_id,"
        " action, before_value, after_value, comment) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (now_str(), actor["email"], actor["role"], module, entity_type, entity_id,
         action, before, after, (comment or "").strip() or None),
    )
    return cur.lastrowid
