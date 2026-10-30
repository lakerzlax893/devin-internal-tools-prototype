"""Data-plane flag reads. Pages call these at request time (no caching), the way product
services would query a flag service; the /flags page is the control plane that writes them."""

import sqlite3

NEW_CHECKOUT = "new_checkout_flow"
INSTANT_PAYOUTS = "instant_payouts"
FRAUD_SCORE_V2 = "fraud_score_v2"
REFUND_SELF_SERVICE = "refund_self_service"
DARK_MODE = "dark_mode_dashboard"


def get_flag(db: sqlite3.Connection, key: str) -> sqlite3.Row | None:
    return db.execute("SELECT * FROM feature_flags WHERE key = ?", (key,)).fetchone()


def flag_on(db: sqlite3.Connection, key: str) -> bool:
    flag = get_flag(db, key)
    return bool(flag is not None and flag["enabled"])
