"""Demo session auth: login/logout routes, current-user dependency, role checks."""

import sqlite3

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.audit import log_audit
from app.db import get_db, verify_password
from app.templating import render

router = APIRouter()


class NotAuthenticated(Exception):
    """Raised by current_user; main.py turns it into a redirect to /login."""


def current_user(request: Request, db: sqlite3.Connection = Depends(get_db)) -> dict:
    user_id = request.session.get("user_id")
    if user_id is None:
        raise NotAuthenticated()
    row = db.execute("SELECT id, name, email, role FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        request.session.clear()
        raise NotAuthenticated()
    user = dict(row)
    request.state.user = user
    return user


def require_admin(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(
            status_code=403,
            detail=f"Forbidden: this action requires the admin role. You are signed in as {user['email']} "
                   f"({user['role']}).",
        )
    return user


@router.get("/login")
def login_form(request: Request):
    if request.session.get("user_id") is not None:
        return RedirectResponse("/", status_code=303)
    return render(request, "login.html")


@router.post("/login")
def login(
    request: Request,
    email: str = Form(""),
    password: str = Form(""),
    db: sqlite3.Connection = Depends(get_db),
):
    email = email.strip().lower()
    row = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if row is None or not verify_password(password, row["password_hash"]):
        return render(request, "login.html", status_code=401,
                      error="Invalid email or password.", email=email)
    request.session.clear()
    request.session["user_id"] = row["id"]
    log_audit(db, dict(row), "auth", "user", row["id"], "login", None, None)
    db.commit()
    return RedirectResponse("/", status_code=303)


@router.api_route("/logout", methods=["GET", "POST"])
def logout(request: Request, db: sqlite3.Connection = Depends(get_db)):
    user_id = request.session.get("user_id")
    if user_id is not None:
        row = db.execute("SELECT id, email, role FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is not None:
            log_audit(db, dict(row), "auth", "user", row["id"], "logout", None, None)
            db.commit()
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
