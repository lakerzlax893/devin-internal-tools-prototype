"""Shared Jinja2 environment, filters, and render/flash helpers."""

import sqlite3
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.db import connect
from app.feature_flags import DARK_MODE, flag_on

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))


def dollars(cents: int | None) -> str:
    cents = int(cents or 0)
    sign = "-" if cents < 0 else ""
    whole, frac = divmod(abs(cents), 100)
    return f"{sign}${whole:,}.{frac:02d}"


def label(value: str | None) -> str:
    return (value or "").replace("_", " ").capitalize()


templates.env.filters["dollars"] = dollars
templates.env.filters["label"] = label
templates.env.filters["date"] = lambda s: (s or "")[:10]


def flash(request: Request, message: str, kind: str = "ok") -> None:
    request.session["flash"] = {"message": message, "kind": kind}


def dark_mode() -> bool:
    """Read the theme flag on every render so a toggle shows on the very next page."""
    try:
        conn = connect()
        try:
            return flag_on(conn, DARK_MODE)
        finally:
            conn.close()
    except sqlite3.Error:
        return False


def render(request: Request, name: str, user: dict | None = None, status_code: int = 200, **context):
    context.update(user=user, flash=request.session.pop("flash", None), dark_mode=dark_mode())
    return templates.TemplateResponse(request, name, context, status_code=status_code)
