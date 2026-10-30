"""App setup: middleware, startup DB init/seed, error handling, home launcher, routers."""

import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from app import auth
from app.auth import NotAuthenticated, current_user
from app.db import get_db, init_db
from app.routers import admin, flags, kyc, refunds
from app.templating import render

BANNER_FLAG_KEY = "homepage_announcement"
BANNER_TEXT = "New internal tools platform — pilot"


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Internal Tools Platform (PoC)", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SESSION_SECRET", "dev-only-insecure-session-secret-change-me"),
    session_cookie="itp_session",
    same_site="lax",
    max_age=8 * 60 * 60,
)
app.mount("/static", StaticFiles(directory=str(Path(__file__).resolve().parent / "static")), name="static")


@app.exception_handler(NotAuthenticated)
async def redirect_to_login(request: Request, _: NotAuthenticated):
    return RedirectResponse("/login", status_code=303)


@app.exception_handler(StarletteHTTPException)
async def html_http_error(request: Request, exc: StarletteHTTPException):
    return render(
        request,
        "error.html",
        user=getattr(request.state, "user", None),
        status_code=exc.status_code,
        status=exc.status_code,
        detail=exc.detail,
    )


app.include_router(auth.router)
app.include_router(kyc.router)
app.include_router(refunds.router)
app.include_router(flags.router)
app.include_router(admin.router)


@app.get("/")
def home(request: Request, user: dict = Depends(current_user), db: sqlite3.Connection = Depends(get_db)):
    count = lambda sql: db.execute(sql).fetchone()[0]  # noqa: E731
    banner_flag = db.execute(
        "SELECT enabled FROM feature_flags WHERE key = ?", (BANNER_FLAG_KEY,)
    ).fetchone()
    tools = [
        {
            "name": "KYC review queue",
            "description": "Review customer identity cases and approve, reject, or request more information.",
            "count": count("SELECT COUNT(*) FROM kyc_cases WHERE status = 'pending'"),
            "count_label": "pending cases",
            "href": "/kyc?status=pending",
        },
        {
            "name": "Refunds dashboard",
            "description": "Track refund requests, approve or deny them, and mark approved refunds as paid.",
            "count": count("SELECT COUNT(*) FROM refunds WHERE status = 'pending'"),
            "count_label": "pending refunds",
            "href": "/refunds?status=pending",
        },
        {
            "name": "Feature-flag admin",
            "description": "View feature flags across environments; admins can toggle them and set rollout %.",
            "count": count("SELECT COUNT(*) FROM feature_flags WHERE enabled = 1"),
            "count_label": "flags enabled",
            "href": "/flags",
        },
    ]
    return render(
        request, "home.html", user=user, active="home", tools=tools,
        banner=BANNER_TEXT if banner_flag is not None and banner_flag["enabled"] else None,
    )
