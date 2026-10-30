"""Customer experience preview: a mock customer/merchant surface whose content is decided
by feature flags read from the database on every request. Not a real customer product."""

import sqlite3

from fastapi import APIRouter, Depends, Request

from app.auth import current_user
from app.db import get_db
from app.feature_flags import FRAUD_SCORE_V2, INSTANT_PAYOUTS, NEW_CHECKOUT, get_flag
from app.templating import render

router = APIRouter()


def _state(db: sqlite3.Connection, key: str) -> dict:
    flag = get_flag(db, key)
    return {"key": key, "on": bool(flag is not None and flag["enabled"]),
            "rollout": flag["rollout_percent"] if flag is not None else 0, "missing": flag is None}


@router.get("/preview")
def preview(request: Request, user: dict = Depends(current_user), db: sqlite3.Connection = Depends(get_db)):
    return render(request, "preview.html", user=user, active="preview",
                  checkout=_state(db, NEW_CHECKOUT), payouts=_state(db, INSTANT_PAYOUTS),
                  fraud=_state(db, FRAUD_SCORE_V2))
