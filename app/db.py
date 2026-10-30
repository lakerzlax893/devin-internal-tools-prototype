"""SQLite connection helpers, schema, and first-run seed data."""

import hashlib
import hmac
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "app.db"
PBKDF2_ITERATIONS = 100_000


def db_path() -> str:
    """Database file path; override with APP_DB_PATH (tests use a temp file)."""
    return os.environ.get("APP_DB_PATH", str(DEFAULT_DB_PATH))


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def get_db():
    """FastAPI dependency: one connection per request."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def now_str(offset: timedelta = timedelta(0)) -> str:
    return (datetime.now(timezone.utc) + offset).strftime("%Y-%m-%d %H:%M:%S")


def hash_password(password: str, salt: str | None = None) -> str:
    """Demo-grade salted PBKDF2-SHA256 hash (stdlib hashlib only)."""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt, digest = stored.split("$")
    except ValueError:
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations))
    return hmac.compare_digest(candidate.hex(), digest)


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('reviewer', 'admin')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kyc_cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_name TEXT NOT NULL,
    email TEXT NOT NULL,
    risk_tier TEXT NOT NULL CHECK (risk_tier IN ('low', 'medium', 'high')),
    status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected', 'info_requested')),
    assignee TEXT,
    submitted_at TEXT NOT NULL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS refunds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_name TEXT NOT NULL,
    email TEXT NOT NULL,
    amount_cents INTEGER NOT NULL CHECK (amount_cents >= 0),
    currency TEXT NOT NULL DEFAULT 'USD',
    reason TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'denied', 'paid')),
    requested_at TEXT NOT NULL,
    transaction_ref TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feature_flags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT,
    environment TEXT NOT NULL CHECK (environment IN ('production', 'staging')),
    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
    rollout_percent INTEGER NOT NULL CHECK (rollout_percent BETWEEN 0 AND 100),
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    actor_email TEXT NOT NULL,
    actor_role TEXT NOT NULL,
    module TEXT NOT NULL CHECK (module IN ('kyc', 'refunds', 'flags', 'auth')),
    entity_type TEXT NOT NULL,
    entity_id INTEGER,
    action TEXT NOT NULL,
    before_value TEXT,
    after_value TEXT,
    comment TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_module ON audit_log (module);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log (entity_type, entity_id);
"""

SEED_USERS = [
    ("Riley Reviewer", "reviewer@example.com", "demo-reviewer", "reviewer"),
    ("Alex Admin", "admin@example.com", "demo-admin", "admin"),
]

# (customer_name, email, risk_tier, status, assignee, days_ago, notes)
SEED_KYC = [
    ("Marisol Vantreese", "marisol.vantreese@example.net", "low", "pending", None, 1, "Standard individual account; passport uploaded."),
    ("Dorian Okafor-Lind", "dorian.ol@example.net", "high", "pending", "Riley Reviewer", 2, "PEP screening hit on similar name; needs manual review."),
    ("Quill & Fern Studio LLC", "ops@quillfern.example.com", "medium", "pending", None, 3, "Business account; beneficial-owner list pending verification."),
    ("Tobias Hrenko", "t.hrenko@example.org", "medium", "info_requested", "Riley Reviewer", 5, "Proof of address older than 90 days."),
    ("Annika Beltrán", "annika.b@example.net", "low", "approved", "Riley Reviewer", 6, "All documents verified automatically."),
    ("Kestrel Logistics Inc", "compliance@kestrel.example.com", "high", "rejected", "Alex Admin", 8, "Registered address resolves to a virtual office; ownership unclear."),
    ("Priya Ramaswell", "priya.ramaswell@example.org", "low", "pending", None, 9, "Selfie match score 0.97."),
    ("Jonah Wexley-Abara", "jonah.wa@example.net", "high", "info_requested", "Alex Admin", 11, "Source-of-funds documentation requested."),
    ("Lucía Marenco", "lucia.marenco@example.com", "medium", "approved", "Alex Admin", 13, "Driver's licence and utility bill verified."),
    ("Bramwell Coffee Roasters", "finance@bramwell.example.com", "low", "approved", None, 16, "Low-volume merchant; standard checks passed."),
    ("Ivo Stanchev", "ivo.stanchev@example.org", "high", "rejected", "Riley Reviewer", 19, "Document tampering suspected on ID image."),
    ("Harriet Oduya", "harriet.oduya@example.net", "medium", "pending", None, 22, "Name mismatch between ID and bank statement (maiden name)."),
    ("Céleste Armitage", "celeste.a@example.com", "low", "info_requested", None, 25, "ID photo blurry; re-upload requested."),
    ("Northgate Ceramics Co", "accounts@northgate.example.com", "medium", "approved", "Riley Reviewer", 28, "Business registry match confirmed."),
]

# (customer_name, email, amount_cents, reason, status, days_ago, transaction_ref)
SEED_REFUNDS = [
    ("Marisol Vantreese", "marisol.vantreese@example.net", 4999, "Duplicate charge", "pending", 1, "TXN-8F3A21"),
    ("Gideon Pratt", "gideon.pratt@example.org", 12500, "Service outage", "pending", 2, "TXN-8F2C97"),
    ("Annika Beltrán", "annika.b@example.net", 1200, "Billing error", "approved", 3, "TXN-8E9D04"),
    ("Wren Callaghan", "wren.c@example.com", 89900, "Damaged item", "pending", 4, "TXN-8E71B5"),
    ("Lucía Marenco", "lucia.marenco@example.com", 2900, "Cancelled subscription", "paid", 6, "TXN-8D55E0"),
    ("Tobias Hrenko", "t.hrenko@example.org", 34050, "Duplicate charge", "denied", 7, "TXN-8D1A6C"),
    ("Priya Ramaswell", "priya.ramaswell@example.org", 7500, "Service outage", "approved", 9, "TXN-8C88F2"),
    ("Bramwell Coffee Roasters", "finance@bramwell.example.com", 45000, "Billing error", "paid", 12, "TXN-8BF013"),
    ("Harriet Oduya", "harriet.oduya@example.net", 15999, "Damaged item", "pending", 15, "TXN-8B3D7A"),
    ("Ezra Mbeki-Holt", "ezra.mh@example.org", 1999, "Cancelled subscription", "denied", 18, "TXN-8A92C1"),
    ("Céleste Armitage", "celeste.a@example.com", 23000, "Duplicate charge", "paid", 21, "TXN-8A0E5F"),
    ("Northgate Ceramics Co", "accounts@northgate.example.com", 61275, "Service outage", "approved", 26, "TXN-89C4D8"),
]

# (key, name, description, environment, enabled, rollout_percent, days_ago)
SEED_FLAGS = [
    ("homepage_announcement", "Homepage announcement banner",
     "Shows the pilot announcement banner on the platform home page.", "production", 1, 100, 2),
    ("new_checkout_flow", "New checkout flow",
     "Routes a share of customers to the redesigned checkout.", "production", 1, 25, 4),
    ("instant_payouts", "Instant payouts",
     "Lets eligible merchants request same-day payouts.", "production", 0, 0, 10),
    ("kyc_auto_approve_low_risk", "KYC auto-approve (low risk)",
     "Auto-approves low-risk KYC cases with a high document-match score.", "staging", 1, 50, 6),
    ("refund_self_service", "Self-service refunds",
     "Allows customers to request refunds from the help centre.", "staging", 0, 10, 14),
    ("dark_mode_dashboard", "Dark mode dashboard",
     "Dark theme for the merchant dashboard.", "staging", 1, 100, 20),
    ("fraud_score_v2", "Fraud score v2",
     "Shadow-scores transactions with the v2 fraud model.", "production", 0, 5, 27),
]


def _table_empty(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def seed(conn: sqlite3.Connection) -> None:
    """Insert fake demo data into any table that is empty (first run only)."""
    if _table_empty(conn, "users"):
        conn.executemany(
            "INSERT INTO users (name, email, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
            [(n, e, hash_password(p), r, now_str()) for n, e, p, r in SEED_USERS],
        )
    if _table_empty(conn, "kyc_cases"):
        conn.executemany(
            "INSERT INTO kyc_cases (customer_name, email, risk_tier, status, assignee, submitted_at, notes)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(n, e, t, s, a, now_str(-timedelta(days=d, hours=i)), notes)
             for i, (n, e, t, s, a, d, notes) in enumerate(SEED_KYC)],
        )
    if _table_empty(conn, "refunds"):
        conn.executemany(
            "INSERT INTO refunds (customer_name, email, amount_cents, currency, reason, status, requested_at,"
            " transaction_ref) VALUES (?, ?, ?, 'USD', ?, ?, ?, ?)",
            [(n, e, c, r, s, now_str(-timedelta(days=d, hours=i)), ref)
             for i, (n, e, c, r, s, d, ref) in enumerate(SEED_REFUNDS)],
        )
    if _table_empty(conn, "feature_flags"):
        conn.executemany(
            "INSERT INTO feature_flags (key, name, description, environment, enabled, rollout_percent, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(k, n, desc, env, en, pct, now_str(-timedelta(days=d)))
             for k, n, desc, env, en, pct, d in SEED_FLAGS],
        )


def init_db() -> None:
    """Create tables if missing and seed empty tables. Safe to call on every startup."""
    Path(db_path()).parent.mkdir(parents=True, exist_ok=True)
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        seed(conn)
        conn.commit()
    finally:
        conn.close()
