"""Module 1: KYC review queue.

External checks (IDV, sanctions & watchlist screening, PEP & adverse media) are
SIMULATED: "Run checks" updates statuses in-app and audits the run, but no
external provider is called.
"""

import sqlite3

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.audit import log_audit
from app.auth import current_user
from app.db import get_db, now_str
from app.templating import flash, label, render

router = APIRouter(prefix="/kyc")

STATUSES = ["pending", "approved", "rejected", "info_requested"]
ACTIONS = {"approve": "approved", "reject": "rejected", "request_info": "info_requested"}

# (column, display name, short name used in audit summaries)
CHECKS = [
    ("idv_status", "Identity verification (IDV)", "idv"),
    ("sanctions_status", "Sanctions & watchlist screening", "sanctions"),
    ("pep_status", "PEP & adverse media", "pep"),
]
CHECK_SEVERITY = {"clear": 0, "not_run": 1, "pending": 2, "review": 3}
INCOMPLETE_CHECKS = {"not_run", "pending"}

# (column, individual label, business label)
DOC_ITEMS = [
    ("doc_government_id", "Government ID", "Certificate of incorporation"),
    ("doc_proof_of_address", "Proof of address", "Proof of registered address"),
    ("doc_selfie_liveness", "Selfie / liveness check", "Authorised person verification"),
    ("doc_source_of_funds", "Source of funds", "Source of funds"),
]
DOC_DONE = {"verified", "received"}

APPROVAL_BLOCKED = "External checks must be completed before approval."


def screening_status(case) -> str:
    """The worse of sanctions and PEP screening: review > pending > not_run > clear."""
    return max(case["sanctions_status"], case["pep_status"], key=CHECK_SEVERITY.__getitem__)


def docs_done(case) -> int:
    return sum(case[col] in DOC_DONE for col, _, _ in DOC_ITEMS)


def checks_incomplete(case) -> bool:
    return any(case[col] in INCOMPLETE_CHECKS for col, _, _ in CHECKS)


def checks_summary(statuses) -> str:
    return ", ".join(f"{short}={statuses[col]}" for col, _, short in CHECKS)


@router.get("")
def kyc_list(
    request: Request,
    status: str = "all",
    user: dict = Depends(current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    status = status if status in STATUSES else "all"
    if status == "all":
        rows = db.execute("SELECT * FROM kyc_cases ORDER BY submitted_at DESC").fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM kyc_cases WHERE status = ? ORDER BY submitted_at DESC", (status,)
        ).fetchall()
    cases = [dict(r, screening=screening_status(r), docs_done=docs_done(r),
                  docs_missing=any(r[col] == "missing" for col, _, _ in DOC_ITEMS)) for r in rows]
    counts = dict(db.execute("SELECT status, COUNT(*) FROM kyc_cases GROUP BY status").fetchall())
    counts["all"] = sum(counts.values())
    return render(request, "kyc_list.html", user=user, active="kyc", cases=cases,
                  status=status, statuses=STATUSES, counts=counts, doc_total=len(DOC_ITEMS))


def _get_case(db: sqlite3.Connection, case_id: int) -> sqlite3.Row:
    case = db.execute("SELECT * FROM kyc_cases WHERE id = ?", (case_id,)).fetchone()
    if case is None:
        raise HTTPException(status_code=404, detail=f"KYC case {case_id} not found.")
    return case


def _render_detail(request: Request, db: sqlite3.Connection, user: dict, case_id: int,
                   error: str | None = None, status_code: int = 200):
    case = _get_case(db, case_id)
    business = case["entity_type"] == "business"
    documents = [(biz_label if business else ind_label, case[col]) for col, ind_label, biz_label in DOC_ITEMS]
    checks = [(name, case[col]) for col, name, _ in CHECKS]
    history = db.execute(
        "SELECT * FROM audit_log WHERE entity_type = 'kyc_case' AND entity_id = ? ORDER BY id DESC",
        (case_id,),
    ).fetchall()
    return render(request, "kyc_detail.html", user=user, active="kyc", status_code=status_code, case=case,
                  documents=documents, checks=checks, checks_incomplete=checks_incomplete(case),
                  docs_done=docs_done(case), doc_total=len(DOC_ITEMS), history=history, error=error)


@router.get("/{case_id}")
def kyc_detail(request: Request, case_id: int, user: dict = Depends(current_user),
               db: sqlite3.Connection = Depends(get_db)):
    return _render_detail(request, db, user, case_id)


@router.post("/{case_id}/run-checks")
def kyc_run_checks(request: Request, case_id: int, user: dict = Depends(current_user),
                   db: sqlite3.Connection = Depends(get_db)):
    """Simulated stand-in for calling an IDV/screening provider: not_run/pending checks
    come back clear; an existing review hit stays review."""
    case = _get_case(db, case_id)
    before = {col: case[col] for col, _, _ in CHECKS}
    after = {col: "clear" if s in INCOMPLETE_CHECKS else s for col, s in before.items()}
    db.execute(
        "UPDATE kyc_cases SET idv_status = ?, sanctions_status = ?, pep_status = ?, checks_last_run_at = ?"
        " WHERE id = ?",
        (after["idv_status"], after["sanctions_status"], after["pep_status"], now_str(), case_id),
    )
    log_audit(db, user, "kyc", "kyc_case", case_id, "checks_run", checks_summary(before), checks_summary(after))
    db.commit()
    flash(request, f"Simulated checks run for {case['case_ref']}: {checks_summary(after)}.")
    return RedirectResponse(f"/kyc/{case_id}", status_code=303)


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
    if action == "approve" and checks_incomplete(case):
        return _render_detail(request, db, user, case_id, error=APPROVAL_BLOCKED, status_code=400)
    db.execute("UPDATE kyc_cases SET status = ? WHERE id = ?", (new_status, case_id))
    log_audit(db, user, "kyc", "kyc_case", case_id, action, case["status"], new_status, comment)
    db.commit()
    flash(request, f"{case['case_ref']} ({case['customer_name']}): {label(case['status'])} → {label(new_status)}.")
    return RedirectResponse(f"/kyc/{case_id}", status_code=303)
