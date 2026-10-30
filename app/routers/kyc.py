"""Module 1: KYC review queue."""

import sqlite3

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.audit import log_audit
from app.auth import current_user
from app.db import get_db
from app.templating import flash, label, render

router = APIRouter(prefix="/kyc")

STATUSES = ["pending", "approved", "rejected", "info_requested"]
ACTIONS = {"approve": "approved", "reject": "rejected", "request_info": "info_requested"}


@router.get("")
def kyc_list(
    request: Request,
    status: str = "all",
    user: dict = Depends(current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    status = status if status in STATUSES else "all"
    if status == "all":
        cases = db.execute("SELECT * FROM kyc_cases ORDER BY submitted_at DESC").fetchall()
    else:
        cases = db.execute(
            "SELECT * FROM kyc_cases WHERE status = ? ORDER BY submitted_at DESC", (status,)
        ).fetchall()
    counts = dict(db.execute("SELECT status, COUNT(*) FROM kyc_cases GROUP BY status").fetchall())
    counts["all"] = sum(counts.values())
    return render(request, "kyc_list.html", user=user, active="kyc", cases=cases,
                  status=status, statuses=STATUSES, counts=counts)


def _get_case(db: sqlite3.Connection, case_id: int) -> sqlite3.Row:
    case = db.execute("SELECT * FROM kyc_cases WHERE id = ?", (case_id,)).fetchone()
    if case is None:
        raise HTTPException(status_code=404, detail=f"KYC case {case_id} not found.")
    return case


@router.get("/{case_id}")
def kyc_detail(request: Request, case_id: int, user: dict = Depends(current_user),
               db: sqlite3.Connection = Depends(get_db)):
    case = _get_case(db, case_id)
    history = db.execute(
        "SELECT * FROM audit_log WHERE entity_type = 'kyc_case' AND entity_id = ? ORDER BY id DESC",
        (case_id,),
    ).fetchall()
    return render(request, "kyc_detail.html", user=user, active="kyc", case=case, history=history)


@router.post("/{case_id}/action")
def kyc_action(
    request: Request,
    case_id: int,
    action: str = Form(""),
    comment: str = Form(""),
    user: dict = Depends(current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    new_status = ACTIONS.get(action)
    if new_status is None:
        raise HTTPException(status_code=400, detail=f"Unknown KYC action '{action}'. "
                                                    f"Use one of: {', '.join(ACTIONS)}.")
    case = _get_case(db, case_id)
    db.execute("UPDATE kyc_cases SET status = ? WHERE id = ?", (new_status, case_id))
    log_audit(db, user, "kyc", "kyc_case", case_id, action, case["status"], new_status, comment)
    db.commit()
    flash(request, f"Case #{case_id} ({case['customer_name']}): {label(case['status'])} → {label(new_status)}.")
    return RedirectResponse(f"/kyc/{case_id}", status_code=303)
