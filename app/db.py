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
    case_ref TEXT NOT NULL UNIQUE,
    customer_name TEXT NOT NULL,
    email TEXT NOT NULL,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('individual', 'business')),
    date_of_birth TEXT,
    nationality TEXT NOT NULL,
    country_of_residence TEXT NOT NULL,
    id_document_type TEXT NOT NULL,
    id_document_last4 TEXT NOT NULL CHECK (length(id_document_last4) <= 4),
    risk_tier TEXT NOT NULL CHECK (risk_tier IN ('low', 'medium', 'high')),
    risk_score INTEGER NOT NULL CHECK (
        (risk_tier = 'low' AND risk_score BETWEEN 0 AND 39)
        OR (risk_tier = 'medium' AND risk_score BETWEEN 40 AND 69)
        OR (risk_tier = 'high' AND risk_score BETWEEN 70 AND 100)
    ),
    status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected', 'info_requested')),
    assignee TEXT,
    submitted_at TEXT NOT NULL,
    notes TEXT,
    doc_government_id TEXT NOT NULL CHECK (doc_government_id IN ('verified', 'received', 'missing', 'not_requested')),
    doc_proof_of_address TEXT NOT NULL CHECK (doc_proof_of_address IN ('verified', 'received', 'missing', 'not_requested')),
    doc_selfie_liveness TEXT NOT NULL CHECK (doc_selfie_liveness IN ('verified', 'received', 'missing', 'not_requested')),
    doc_source_of_funds TEXT NOT NULL CHECK (doc_source_of_funds IN ('verified', 'received', 'missing', 'not_requested')),
    idv_status TEXT NOT NULL CHECK (idv_status IN ('clear', 'review', 'not_run', 'pending')),
    sanctions_status TEXT NOT NULL CHECK (sanctions_status IN ('clear', 'review', 'not_run', 'pending')),
    pep_status TEXT NOT NULL CHECK (pep_status IN ('clear', 'review', 'not_run', 'pending')),
    checks_last_run_at TEXT
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
    ("Riley Chen", "reviewer@example.com", "demo-reviewer", "reviewer"),
    ("Alex Morgan", "admin@example.com", "demo-admin", "admin"),
]

RILEY = "Riley Chen"
ALEX = "Alex Morgan"
V, R, M, NR = "verified", "received", "missing", "not_requested"


def _kyc(name, email, entity, dob, nationality, residence, doc_type, last4, tier, score, status, assignee,
         days_ago, notes, docs, checks, checks_days_ago):
    """One seeded KYC case. docs = (government_id, proof_of_address, selfie_liveness, source_of_funds);
    checks = (idv, sanctions, pep); checks_days_ago = None means checks never run."""
    return dict(customer_name=name, email=email, entity_type=entity, date_of_birth=dob, nationality=nationality,
                country_of_residence=residence, id_document_type=doc_type, id_document_last4=last4,
                risk_tier=tier, risk_score=score, status=status, assignee=assignee, days_ago=days_ago, notes=notes,
                doc_government_id=docs[0], doc_proof_of_address=docs[1], doc_selfie_liveness=docs[2],
                doc_source_of_funds=docs[3], idv_status=checks[0], sanctions_status=checks[1], pep_status=checks[2],
                checks_days_ago=checks_days_ago)


# All values are fake. Case refs are assigned in order: KYC-2026-0158 (first) down to KYC-2026-0145.
SEED_KYC = [
    _kyc("Marisol Vantreese", "marisol.vantreese@example.net", "individual", "1991-04-17", "Spain", "United Kingdom",
         "Passport", "4821", "low", 18, "pending", None, 1,
         "Standard individual account; passport and utility bill verified, low expected volume.",
         (V, V, V, NR), ("clear", "clear", "clear"), 1),
    _kyc("Dorian Okafor-Lind", "dorian.ol@example.net", "individual", "1978-11-02", "Nigeria", "Sweden",
         "Passport", "7730", "high", 82, "pending", RILEY, 2,
         "Possible PEP match on a similar name (regional official); high expected volume. Needs analyst review.",
         (V, V, V, R), ("clear", "clear", "review"), 2),
    _kyc("Quill & Fern Studio LLC", "ops@quillfern.example.com", "business", None, "United States", "United States",
         "Certificate of incorporation", "19QF", "medium", 55, "pending", None, 3,
         "Business account; beneficial-owner list pending verification. Sanctions screening not yet run.",
         (V, R, NR, M), ("clear", "not_run", "clear"), 3),
    _kyc("Tobias Hrenko", "t.hrenko@example.org", "individual", "1986-07-23", "Czechia", "Germany",
         "National ID", "0394", "medium", 47, "info_requested", RILEY, 5,
         "Proof of address older than 90 days; new document requested.",
         (V, M, V, NR), ("clear", "clear", "clear"), 5),
    _kyc("Annika Beltrán", "annika.b@example.net", "individual", "1995-01-30", "Argentina", "Spain",
         "Passport", "5512", "low", 12, "approved", RILEY, 6,
         "All documents verified; no screening hits.",
         (V, V, V, NR), ("clear", "clear", "clear"), 6),
    _kyc("Kestrel Logistics Inc", "compliance@kestrel.example.com", "business", None, "Cyprus", "Cyprus",
         "Certificate of incorporation", "88KL", "high", 88, "rejected", ALEX, 8,
         "Registered address resolves to a virtual office; ownership unclear; possible sanctions-list match on a director.",
         (V, R, NR, M), ("clear", "review", "clear"), 8),
    _kyc("Priya Ramaswell", "priya.ramaswell@example.org", "individual", "1989-09-12", "India", "Canada",
         "Driver's licence", "2207", "low", 24, "pending", None, 9,
         "Selfie match score 0.97. PEP & adverse-media screening not yet run.",
         (V, V, V, NR), ("clear", "clear", "not_run"), 9),
    _kyc("Jonah Wexley-Abara", "jonah.wa@example.net", "individual", "1972-03-08", "Kenya", "United Kingdom",
         "Passport", "6648", "high", 76, "info_requested", ALEX, 11,
         "Large initial deposit expected; source-of-funds documentation requested.",
         (V, V, V, M), ("clear", "clear", "clear"), 11),
    _kyc("Lucía Marenco", "lucia.marenco@example.com", "individual", "1993-06-25", "Mexico", "United States",
         "Driver's licence", "9135", "medium", 44, "approved", ALEX, 13,
         "Driver's licence and utility bill verified; moderate cross-border volume.",
         (V, V, V, R), ("clear", "clear", "clear"), 13),
    _kyc("Bramwell Coffee Roasters", "finance@bramwell.example.com", "business", None, "United Kingdom", "United Kingdom",
         "Certificate of incorporation", "07BR", "low", 22, "approved", None, 16,
         "Low-volume merchant; registry match confirmed, standard checks passed.",
         (V, V, NR, NR), ("clear", "clear", "clear"), 16),
    _kyc("Ivo Stanchev", "ivo.stanchev@example.org", "individual", "1984-12-14", "Bulgaria", "Bulgaria",
         "National ID", "3071", "high", 91, "rejected", RILEY, 19,
         "Document tampering suspected on ID image; IDV flagged for review.",
         (R, V, V, NR), ("review", "clear", "clear"), 19),
    _kyc("Harriet Oduya", "harriet.oduya@example.net", "individual", "1990-02-19", "Ghana", "Ireland",
         "Passport", "1186", "medium", 58, "pending", None, 22,
         "Name mismatch between ID and bank statement (maiden name). IDV result pending from provider.",
         (V, R, V, NR), ("pending", "clear", "clear"), 22),
    _kyc("Céleste Armitage", "celeste.a@example.com", "individual", "1998-08-04", "France", "France",
         "National ID", "7402", "low", 30, "info_requested", None, 25,
         "ID photo blurry; re-upload requested before IDV can run.",
         (M, V, R, NR), ("not_run", "clear", "clear"), None),
    _kyc("Northgate Ceramics Co", "accounts@northgate.example.com", "business", None, "Ireland", "Ireland",
         "Certificate of incorporation", "52NC", "medium", 41, "approved", RILEY, 28,
         "Business registry match confirmed; two beneficial owners verified.",
         (V, V, NR, R), ("clear", "clear", "clear"), 27),
]
KYC_FIRST_REF_NUMBER = 158

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
     "Dark theme for this platform's own internal UI.", "staging", 0, 100, 20),
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
        for i, case in enumerate(SEED_KYC):
            row = {k: v for k, v in case.items() if k not in ("days_ago", "checks_days_ago")}
            row["case_ref"] = f"KYC-2026-{KYC_FIRST_REF_NUMBER - i:04d}"
            row["submitted_at"] = now_str(-timedelta(days=case["days_ago"], hours=i))
            row["checks_last_run_at"] = (None if case["checks_days_ago"] is None
                                         else now_str(-timedelta(days=case["checks_days_ago"], hours=i - 1)))
            cols = ", ".join(row)
            conn.execute(f"INSERT INTO kyc_cases ({cols}) VALUES ({', '.join('?' * len(row))})", tuple(row.values()))
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
        kyc_columns = {r[1] for r in conn.execute("PRAGMA table_info(kyc_cases)")}
        if "case_ref" not in kyc_columns:
            raise RuntimeError(
                f"{db_path()} was created by an older version of this prototype (kyc_cases has no case_ref "
                "column). Stop the server, delete that file, and start again to recreate and reseed it."
            )
        seed(conn)
        conn.commit()
    finally:
        conn.close()
