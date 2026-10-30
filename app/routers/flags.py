"""Module 3: Feature-flag admin. Everyone can view; only admins can change."""

import sqlite3

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.audit import log_audit
from app.auth import current_user, require_admin
from app.db import get_db, now_str
from app.templating import flash, render

router = APIRouter(prefix="/flags")

TRUTHY = {"1", "true", "on", "yes"}

# What each flag changes in this app (the data plane). Shown on the flags page.
FLAG_CONTROLS = {
    "homepage_announcement": "Home page announcement banner",
    "new_checkout_flow": "Preview page: new vs classic checkout",
    "instant_payouts": "Preview page: instant vs standard payouts panel",
    "fraud_score_v2": "Preview page: fraud-scoring badge (shadow)",
    "refund_self_service": "Refunds page: self-service request form",
    "dark_mode_dashboard": "This platform's own theme (light/dark)",
    "kyc_auto_approve_low_risk": "Not wired in this prototype — recorded only",
}
NOT_WIRED = "Not wired in this prototype — recorded only"


def describe(enabled: int | bool, rollout: int) -> str:
    return f"enabled={'true' if enabled else 'false'}, rollout={rollout}"


@router.get("")
def flags_list(request: Request, user: dict = Depends(current_user), db: sqlite3.Connection = Depends(get_db)):
    flags = db.execute("SELECT * FROM feature_flags ORDER BY environment, key").fetchall()
    return render(request, "flags_list.html", user=user, active="flags", flags=flags,
                  is_admin=user["role"] == "admin", controls=FLAG_CONTROLS, not_wired=NOT_WIRED)


@router.post("/{flag_id}/update")
def flag_update(
    request: Request,
    flag_id: int,
    enabled: str = Form("0"),
    rollout_percent: str = Form(""),
    comment: str = Form(""),
    user: dict = Depends(require_admin),
    db: sqlite3.Connection = Depends(get_db),
):
    flag = db.execute("SELECT * FROM feature_flags WHERE id = ?", (flag_id,)).fetchone()
    if flag is None:
        raise HTTPException(status_code=404, detail=f"Feature flag {flag_id} not found.")
    try:
        rollout = int(rollout_percent.strip())
    except ValueError:
        rollout = -1
    if not 0 <= rollout <= 100:
        raise HTTPException(status_code=400,
                            detail=f"Rollout % must be a whole number from 0 to 100 (got '{rollout_percent}').")
    new_enabled = 1 if enabled.strip().lower() in TRUTHY else 0

    before = describe(flag["enabled"], flag["rollout_percent"])
    after = describe(new_enabled, rollout)
    db.execute(
        "UPDATE feature_flags SET enabled = ?, rollout_percent = ?, updated_at = ? WHERE id = ?",
        (new_enabled, rollout, now_str(), flag_id),
    )
    log_audit(db, user, "flags", "feature_flag", flag_id, "update", before, after, comment)
    db.commit()
    flash(request, f"Flag '{flag['key']}': {before} → {after}.")
    return RedirectResponse("/flags", status_code=303)
