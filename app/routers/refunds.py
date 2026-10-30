"""Module 2: Refunds dashboard."""

import sqlite3

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.audit import log_audit
from app.auth import current_user
from app.db import get_db
from app.templating import flash, label, render

router = APIRouter(prefix="/refunds")

STATUSES = ["pending", "approved", "denied", "paid"]
ACTIONS = {"approve": "approved", "deny": "denied", "mark_paid": "paid"}


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
                  status=status, statuses=STATUSES, counts=counts, summary=summary(db))


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
