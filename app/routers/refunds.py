"""Module 2: Refunds dashboard."""

import sqlite3

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.audit import log_audit
from app.auth import current_user
from app.db import get_db, now_str
from app.feature_flags import REFUND_SELF_SERVICE, flag_on
from app.templating import flash, label, render

router = APIRouter(prefix="/refunds")

STATUSES = ["pending", "approved", "denied", "paid"]
ACTIONS = {"approve": "approved", "deny": "denied", "mark_paid": "paid"}
REASONS = ["Duplicate charge", "Service outage", "Billing error", "Damaged item", "Cancelled subscription"]
MAX_REFUND_CENTS = 1_000_000


def summary(db: sqlite3.Connection) -> dict:
    row = db.execute(
        """
        SELECT
            COALESCE(SUM(amount_cents), 0) AS total_requested,
            COALESCE(SUM(CASE WHEN status IN ('approved', 'paid') THEN amount_cents END), 0) AS total_approved,
            COALESCE(SUM(CASE WHEN status = 'paid' THEN amount_cents END), 0) AS total_paid,
            COUNT(CASE WHEN status = 'pending' THEN 1 END) AS pending_count
        FROM refunds
        """
    ).fetchone()
    return dict(row)


@router.get("")
def refunds_list(
    request: Request,
    status: str = "all",
    user: dict = Depends(current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    status = status if status in STATUSES else "all"
    if status == "all":
        refunds = db.execute("SELECT * FROM refunds ORDER BY requested_at DESC").fetchall()
    else:
        refunds = db.execute(
            "SELECT * FROM refunds WHERE status = ? ORDER BY requested_at DESC", (status,)
        ).fetchall()
    counts = dict(db.execute("SELECT status, COUNT(*) FROM refunds GROUP BY status").fetchall())
    counts["all"] = sum(counts.values())
    return render(request, "refunds_list.html", user=user, active="refunds", refunds=refunds,
                  status=status, statuses=STATUSES, counts=counts, summary=summary(db),
                  self_service=flag_on(db, REFUND_SELF_SERVICE), reasons=REASONS)


def _parse_cents(amount: str) -> int:
    try:
        cents = round(float(amount.strip().lstrip("$").replace(",", "")) * 100)
    except ValueError:
        cents = 0
    if not 0 < cents <= MAX_REFUND_CENTS:
        raise HTTPException(status_code=400, detail=f"Amount must be between $0.01 and "
                                                    f"${MAX_REFUND_CENTS // 100:,} (got '{amount}').")
    return cents


@router.post("/new")
def refund_new(
    request: Request,
    customer_name: str = Form(""),
    email: str = Form(""),
    amount: str = Form(""),
    reason: str = Form(""),
    user: dict = Depends(current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """Self-service refund request (simulation), gated server-side by refund_self_service."""
    if not flag_on(db, REFUND_SELF_SERVICE):
        raise HTTPException(status_code=403, detail="Self-service refund requests are disabled: feature flag "
                                                    f"{REFUND_SELF_SERVICE} is OFF. Nothing was created.")
    customer_name, email = customer_name.strip(), email.strip()
    if not customer_name or "@" not in email or reason not in REASONS:
        raise HTTPException(status_code=400, detail="Customer name, a valid email, and a reason from the list "
                                                    "are required.")
    cents = _parse_cents(amount)
    n = db.execute("SELECT COUNT(*) FROM refunds WHERE transaction_ref LIKE 'TXN-DEMO-%'").fetchone()[0] + 1
    ref = f"TXN-DEMO-{n:04d}"
    cur = db.execute(
        "INSERT INTO refunds (customer_name, email, amount_cents, currency, reason, status, requested_at,"
        " transaction_ref) VALUES (?, ?, ?, 'USD', ?, 'pending', ?, ?)",
        (customer_name, email, cents, reason, now_str(), ref),
    )
    log_audit(db, user, "refunds", "refund", cur.lastrowid, "created", None, "pending",
              f"Self-service request (simulation) {ref}: {label(reason)}")
    db.commit()
    flash(request, f"Refund request {ref} created for {customer_name} — pending review.")
    return RedirectResponse(f"/refunds/{cur.lastrowid}", status_code=303)


def _get_refund(db: sqlite3.Connection, refund_id: int) -> sqlite3.Row:
    refund = db.execute("SELECT * FROM refunds WHERE id = ?", (refund_id,)).fetchone()
    if refund is None:
        raise HTTPException(status_code=404, detail=f"Refund {refund_id} not found.")
    return refund


@router.get("/{refund_id}")
def refund_detail(request: Request, refund_id: int, user: dict = Depends(current_user),
                  db: sqlite3.Connection = Depends(get_db)):
    refund = _get_refund(db, refund_id)
    history = db.execute(
        "SELECT * FROM audit_log WHERE entity_type = 'refund' AND entity_id = ? ORDER BY id DESC",
        (refund_id,),
    ).fetchall()
    return render(request, "refund_detail.html", user=user, active="refunds", refund=refund, history=history)


@router.post("/{refund_id}/action")
def refund_action(
    request: Request,
    refund_id: int,
    action: str = Form(""),
    comment: str = Form(""),
    user: dict = Depends(current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    new_status = ACTIONS.get(action)
    if new_status is None:
        raise HTTPException(status_code=400, detail=f"Unknown refund action '{action}'. "
                                                    f"Use one of: {', '.join(ACTIONS)}.")
    refund = _get_refund(db, refund_id)
    db.execute("UPDATE refunds SET status = ? WHERE id = ?", (new_status, refund_id))
    log_audit(db, user, "refunds", "refund", refund_id, action, refund["status"], new_status, comment)
    db.commit()
    flash(request, f"Refund #{refund_id} ({refund['customer_name']}): "
                   f"{label(refund['status'])} → {label(new_status)}.")
    return RedirectResponse(f"/refunds/{refund_id}", status_code=303)
