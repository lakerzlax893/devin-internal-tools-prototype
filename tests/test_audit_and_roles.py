"""Audit-log and role-enforcement tests. Each test gets a fresh temp SQLite file
via APP_DB_PATH, so the real app.db is never read or modified."""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import db as app_db
from app.main import BANNER_TEXT, app

REVIEWER = ("reviewer@example.com", "demo-reviewer")
ADMIN = ("admin@example.com", "demo-admin")


@pytest.fixture()
def db_file(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setenv("APP_DB_PATH", str(path))
    assert app_db.db_path() == str(path) != str(app_db.DEFAULT_DB_PATH)
    return path


@pytest.fixture()
def client(db_file):
    with TestClient(app) as c:  # context manager runs the startup hook (create + seed)
        yield c


def login(client, creds):
    email, password = creds
    r = client.post("/login", data={"email": email, "password": password}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"


def query(db_file, sql, params=()):
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def audit_for(db_file, entity_type, entity_id):
    return query(db_file, "SELECT * FROM audit_log WHERE entity_type = ? AND entity_id = ?",
                 (entity_type, entity_id))


def first_id(db_file, table, where):
    return query(db_file, f"SELECT id FROM {table} WHERE {where} ORDER BY id LIMIT 1")[0]["id"]


# (1)
def test_reviewer_approving_kyc_case_writes_one_audit_entry(client, db_file):
    login(client, REVIEWER)
    case_id = first_id(db_file, "kyc_cases", "status = 'pending'")

    r = client.post(f"/kyc/{case_id}/action", data={"action": "approve", "comment": "docs verified"},
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/kyc/{case_id}"

    assert query(db_file, "SELECT status FROM kyc_cases WHERE id = ?", (case_id,))[0]["status"] == "approved"
    entries = audit_for(db_file, "kyc_case", case_id)
    assert len(entries) == 1
    e = entries[0]
    assert (e["module"], e["action"], e["before_value"], e["after_value"]) == ("kyc", "approve", "pending", "approved")
    assert (e["actor_email"], e["actor_role"], e["comment"]) == ("reviewer@example.com", "reviewer", "docs verified")
    assert "Approved" in client.get(f"/kyc/{case_id}").text


# (2)
@pytest.mark.parametrize("action,expected", [("approve", "approved"), ("mark_paid", "paid")])
def test_refund_action_writes_one_audit_entry(client, db_file, action, expected):
    login(client, REVIEWER)
    refund_id = first_id(db_file, "refunds", "status = 'pending'")

    r = client.post(f"/refunds/{refund_id}/action", data={"action": action}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/refunds/{refund_id}"

    assert query(db_file, "SELECT status FROM refunds WHERE id = ?", (refund_id,))[0]["status"] == expected
    entries = audit_for(db_file, "refund", refund_id)
    assert len(entries) == 1
    e = entries[0]
    assert (e["module"], e["before_value"], e["after_value"]) == ("refunds", "pending", expected)
    assert e["actor_email"] == "reviewer@example.com"


# (3)
def test_reviewer_cannot_update_flag(client, db_file):
    login(client, REVIEWER)
    before = query(db_file, "SELECT * FROM feature_flags WHERE key = 'homepage_announcement'")[0]
    flags_audit_before = len(query(db_file, "SELECT id FROM audit_log WHERE module = 'flags'"))

    r = client.post(f"/flags/{before['id']}/update", data={"enabled": "0", "rollout_percent": "10"})
    assert r.status_code == 403
    assert "admin" in r.text.lower()

    after = query(db_file, "SELECT * FROM feature_flags WHERE id = ?", (before["id"],))[0]
    assert dict(after) == dict(before)
    assert len(query(db_file, "SELECT id FROM audit_log WHERE module = 'flags'")) == flags_audit_before
    assert audit_for(db_file, "feature_flag", before["id"]) == []


# (4)
def test_admin_toggling_flag_writes_one_audit_entry(client, db_file):
    login(client, ADMIN)
    flag = query(db_file, "SELECT * FROM feature_flags WHERE key = 'homepage_announcement'")[0]
    assert flag["enabled"] == 1

    r = client.post(f"/flags/{flag['id']}/update",
                    data={"enabled": "0", "rollout_percent": str(flag["rollout_percent"])},
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/flags"

    assert query(db_file, "SELECT enabled FROM feature_flags WHERE id = ?", (flag["id"],))[0]["enabled"] == 0
    entries = audit_for(db_file, "feature_flag", flag["id"])
    assert len(entries) == 1
    e = entries[0]
    pct = flag["rollout_percent"]
    assert e["before_value"] == f"enabled=true, rollout={pct}"
    assert e["after_value"] == f"enabled=false, rollout={pct}"
    assert (e["module"], e["actor_email"], e["actor_role"]) == ("flags", "admin@example.com", "admin")


# (5)
def test_unauthenticated_kyc_redirects_to_login(client):
    r = client.get("/kyc", follow_redirects=False)
    assert r.status_code in (302, 303, 307)
    assert r.headers["location"] == "/login"


# Extra coverage beyond the five required tests.
def test_audit_csv_is_admin_only(client):
    login(client, REVIEWER)
    client.post("/kyc/1/action", data={"action": "reject"})
    assert client.get("/admin/audit.csv").status_code == 403
    client.post("/logout")

    login(client, ADMIN)
    r = client.get("/admin/audit.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    lines = r.text.strip().splitlines()
    assert lines[0].startswith("id,created_at,actor_email,actor_role,module")
    assert any("kyc_case" in line and "reviewer@example.com" in line for line in lines[1:])


def test_homepage_banner_follows_flag(client, db_file):
    login(client, ADMIN)
    assert BANNER_TEXT in client.get("/").text
    flag_id = first_id(db_file, "feature_flags", "key = 'homepage_announcement'")
    client.post(f"/flags/{flag_id}/update", data={"enabled": "0", "rollout_percent": "100"})
    assert BANNER_TEXT not in client.get("/").text


def test_admin_flag_update_rejects_invalid_rollout(client, db_file):
    login(client, ADMIN)
    flag_id = first_id(db_file, "feature_flags", "key = 'homepage_announcement'")
    r = client.post(f"/flags/{flag_id}/update", data={"enabled": "1", "rollout_percent": "150"})
    assert r.status_code == 400
    assert audit_for(db_file, "feature_flag", flag_id) == []


def test_bad_login_shows_error(client):
    r = client.post("/login", data={"email": "reviewer@example.com", "password": "wrong"})
    assert r.status_code == 401
    assert "Invalid email or password" in r.text
