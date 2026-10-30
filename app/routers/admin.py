"""Shared audit log page (all roles) and CSV export (admin only)."""

import csv
import io
import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from app.audit import MODULES
from app.auth import current_user, require_admin
from app.db import get_db
from app.templating import render

router = APIRouter()

CSV_COLUMNS = ["id", "created_at", "actor_email", "actor_role", "module", "entity_type", "entity_id",
               "action", "before_value", "after_value", "comment"]
ENTITY_LINKS = {"kyc_case": "/kyc/{}", "refund": "/refunds/{}", "feature_flag": "/flags"}


@router.get("/audit")
def audit_page(
    request: Request,
    module: str = "all",
    user: dict = Depends(current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    module = module if module in MODULES else "all"
    if module == "all":
        entries = db.execute("SELECT * FROM audit_log ORDER BY id DESC").fetchall()
    else:
        entries = db.execute("SELECT * FROM audit_log WHERE module = ? ORDER BY id DESC", (module,)).fetchall()
    flag_keys = dict(db.execute("SELECT id, key FROM feature_flags").fetchall())
    return render(request, "audit.html", user=user, active="audit", entries=entries, module=module,
                  modules=MODULES, entity_links=ENTITY_LINKS, flag_keys=flag_keys,
                  is_admin=user["role"] == "admin")


@router.get("/admin/audit.csv")
def audit_csv(user: dict = Depends(require_admin), db: sqlite3.Connection = Depends(get_db)):
    rows = db.execute(f"SELECT {', '.join(CSV_COLUMNS)} FROM audit_log ORDER BY id DESC").fetchall()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_COLUMNS)
    writer.writerows([tuple(r) for r in rows])
    filename = f"audit_log_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
