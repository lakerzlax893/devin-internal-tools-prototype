# Internal Tools Platform — proof of concept

## 1. What this is

A proof-of-concept internal-tools platform that replicates the core functionality of three Microsoft Power Apps — a **KYC review queue**, a **refunds dashboard**, and a **feature-flag admin panel** — as modules of one FastAPI web application. All three share one authentication layer, one SQLite database, one audit log, and one base template, so each additional tool is mostly a new table plus a few routes and templates. It was built with Devin and runs locally with seeded **fake data only**: no real customer data, no external services, no payment or identity-provider integrations. Authentication is demo-grade (see below).

## 2. How to run it

Requires Python 3.10+.

```bash
./run.sh
```

`run.sh` creates `./.venv` if needed, installs `requirements.txt` if it has not been installed (or has changed), and then runs the standard command. If you manage dependencies yourself, the run command from the repo root is exactly:

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open **http://127.0.0.1:8000**. On first startup the app creates `app.db` in the repo root and seeds it (tables use `CREATE TABLE IF NOT EXISTS` and seeding only fills empty tables, so restarts keep your changes). To reset to fresh demo data, stop the server and delete `app.db`. **Upgrading from an earlier checkout:** the KYC table gained new columns, so an `app.db` created by an older version must be deleted once (the app refuses to start against it with a message saying so); it is recreated and reseeded on the next start. `dark_mode_dashboard` is now seeded **OFF** (it switches this platform's own theme); an older `app.db` keeps it ON until you delete it or turn it off on the flags page.

| Login | Password | Role | Can | Cannot |
|---|---|---|---|---|
| `reviewer@example.com` (Riley Chen) | `demo-reviewer` | reviewer | Use the KYC queue and refunds dashboard (list, filter, view, approve/reject/etc.); view feature flags read-only; view the audit log | Change feature flags (HTTP 403); download the audit CSV (HTTP 403) |
| `admin@example.com` (Alex Morgan) | `demo-admin` | admin | Everything the reviewer can, plus change feature flags and download the audit CSV | — |

**Demo auth notice:** passwords are stored as salted PBKDF2-SHA256 hashes using Python's standard-library `hashlib`, and sessions are signed cookies (Starlette `SessionMiddleware`). The default signing key is a hard-coded development value; set `SESSION_SECRET` to override it. There is no CSRF token, rate limiting, lockout, or MFA. This is not production authentication.

Optional environment variables: `APP_DB_PATH` (SQLite file path, default `./app.db`), `SESSION_SECRET`.

## 3. Demo walk-through

1. Open http://127.0.0.1:8000 — you are redirected to `/login`. Sign in as **reviewer@example.com / demo-reviewer**. The home page shows the "New internal tools platform — pilot" banner and three tool cards with live counts.
2. Click **KYC review queue** (or the *Pending* filter). Each row shows the case ref, applicant type, risk tier and score, IDV and screening badges (simulated), and how many of the four checklist documents are in. Open **Marisol Vantreese (KYC-2026-0158)** — all checks are Clear — type a comment, and click **Approve**. The detail page shows the new status and the case's audit history. Open **Audit log** — the newest entry shows you, module `kyc`, `pending → approved`, and your comment.
3. Still in the KYC queue, open **Quill & Fern Studio LLC (KYC-2026-0156)**: in the *External checks (simulated)* panel, sanctions screening is **Not run**. Click **Approve** — it is refused with "External checks must be completed before approval." and nothing changes. Click **Run checks**: the Not run check becomes **Clear**, *Last run* updates, and one `checks_run` entry appears in the case's audit history. Now **Approve** succeeds. (On **Dorian Okafor-Lind (KYC-2026-0157)**, PEP & adverse media is **Review**; running checks again leaves it at Review — a real hit does not clear itself.) Run checks is a simulated stand-in for calling an IDV/screening provider API: the workflow (trigger, status change, approval gate, audit) is real; the provider response is stubbed in-app.
4. Open **Refunds**, note the four summary figures, open a pending refund and click **Approve**. Back on the dashboard, *Total approved* has increased by that amount and *Pending refunds* has dropped by one. (Click **Mark paid** on the same refund to see *Total paid* change too.)
5. Open **Feature flags**. As a reviewer the list is read-only with a note that changes are admin-only. The server enforces this too — e.g. `curl -X POST` to `/flags/1/update` with a reviewer session returns **403 Forbidden** and writes nothing. Visiting http://127.0.0.1:8000/admin/audit.csv also returns 403.
6. Click **Log out**, sign in as **admin@example.com / demo-admin**, open **Feature flags**, and click **Turn OFF** on `homepage_announcement`. Go **Home** — the banner is gone. Turn it back **ON** and the banner reappears. (You can also set ON/OFF and a rollout % with the Save form; rollout must be 0–100.)
7. Still as admin, see flags drive real behaviour (each flag's **Controls** line on the flags page says what it changes):
   - Open **Preview** (a simulated customer/merchant surface, not a real product) — it shows *New checkout*. On **Feature flags**, **Turn OFF** `new_checkout_flow`, reopen **Preview**: it now shows *Classic checkout*, and the line under the panel reads "Served by flag new_checkout_flow — OFF".
   - **Turn ON** `refund_self_service`, open **Refunds**: a *New refund request (self-service simulation)* form appears. Submit one — it is created as **pending** with a `TXN-DEMO-####` ref and a `created` entry appears in the audit log. With the flag OFF the form is replaced by a note, and the server refuses `POST /refunds/new` with 403.
   - **Turn ON** `dark_mode_dashboard`: the flags page re-renders in the dark theme straight away; turn it OFF to go back.
8. Open **Audit log**: every action above is listed newest-first with actor, module, entity, before → after, and comment. Filter by module with the pills (`?module=kyc|refunds|flags|auth`). As admin, click **Download CSV** to export the full log.

## 4. How the platform is structured

```
app/
  main.py        app setup, session middleware, startup create+seed hook, error pages, home launcher
  db.py          sqlite3 connection helper (get_db dependency), schema, password hashing, seed data
  auth.py        /login, /logout, current_user dependency, require_admin dependency
  audit.py       log_audit() — the single audit helper
  feature_flags.py  get_flag() / flag_on() — request-time flag reads for pages
  templating.py  shared Jinja2 environment, filters (dollars, label, date), render() and flash()
  routers/
    kyc.py       Module 1: /kyc, /kyc/{id}, POST /kyc/{id}/run-checks (simulated), POST /kyc/{id}/action
    refunds.py   Module 2: /refunds, /refunds/{id}, POST /refunds/{id}/action, POST /refunds/new (flag-gated)
    flags.py     Module 3: /flags, POST /flags/{id}/update (admin only); FLAG_CONTROLS says what each flag drives
    preview.py   /preview — customer experience preview (simulation) driven by flags
    admin.py     /audit (all roles), /admin/audit.csv (admin only)
  templates/     base.html layout + one list/detail template per module, shared macros in _filters.html
  static/style.css
tests/test_audit_and_roles.py
```

The shared layer every module uses:

- **Auth** — each route declares `user = Depends(current_user)` (any signed-in user) or `Depends(require_admin)` (admin only, otherwise 403). Unauthenticated requests raise `NotAuthenticated`, which `main.py` turns into a redirect to `/login`. Role checks are server-side; hiding buttons in templates is cosmetic only.
- **Database** — one SQLite file, one `get_db` dependency giving each request its own connection. The path comes from `APP_DB_PATH` so tests can point at a temp file.
- **Audit** — `log_audit(db, actor, module, entity_type, entity_id, action, before, after, comment)` inserts one row and does **not** commit; each action handler updates its row, calls `log_audit`, then commits once, so the change and its audit record succeed or fail together.
- **Feature flags: control plane vs data plane** — the flags page is the *control plane*: it records each flag's on/off state and rollout %. Pages that read a flag at a decision point and behave differently are the *data plane*. In production, the customer-facing product services would query the flag service the same way these pages query the database. Here the data plane is the platform home page (announcement banner), the refunds page (self-service request form, also enforced server-side on `POST /refunds/new`), the platform's own UI theme (`dark_mode_dashboard`, read in `render()`), and the **Preview** page (checkout, payouts, fraud-scoring panels). Flags are read from the database on every request — no caching — so a toggle takes effect on the next page load. Rollout % is recorded only; nothing buckets users by it. `kyc_auto_approve_low_risk` is deliberately not wired — the flags page says so.
- **UI** — `base.html` provides the nav, the signed-in user's name/role and logout button, and flash messages; `render()` injects the user and flash into every page. All actions are plain HTML form POSTs followed by a 303 redirect — no JavaScript required.

## 5. How tool #4 would be built

Example: an **expenses approval queue**.

1. **Table** — add `CREATE TABLE IF NOT EXISTS expenses (id, employee_name, email, amount_cents, category, status CHECK (status IN ('pending','approved','rejected','reimbursed')), submitted_at, receipt_ref, notes)` to `SCHEMA` in `db.py`, plus a seed list.
2. **Router** — copy `routers/refunds.py` to `routers/expenses.py` and change the table name, `STATUSES`, and `ACTIONS` map (`approve → approved`, `reject → rejected`, `reimburse → reimbursed`). The list/filter/detail/action shape, `current_user`/`require_admin` dependencies, and the `log_audit(db, user, "expenses", "expense", id, action, before, after, comment)` call stay the same. Add `"expenses"` to `MODULES` in `audit.py` and to the `audit_log.module` CHECK constraint.
3. **Templates** — copy `refunds_list.html` / `refund_detail.html`; the status filter pills and audit-history table are shared macros, and the layout, nav, styles, and flash messages come from `base.html` for free.
4. **Wire up** — `app.include_router(expenses.router)` in `main.py`, a nav link in `base.html`, and a card on the home page. Copy two tests from `tests/test_audit_and_roles.py`.

Why that is faster than tool #1: login, sessions, role enforcement, the database connection, the audit log (including its page, filter, and CSV export), error pages, the layout, and the styling are already built and tested. Tool #1 had to establish all of that; tool #4 is a new table, ~80 lines of router code following an existing pattern, and two templates — and every new tool's actions show up in the same audit trail automatically. Moving to production later (SSO, Postgres) is a change to the shared layer that every tool inherits, not a per-tool rewrite.

## 6. What was deliberately not built and why

This is a pattern prototype. The following are intentionally out of scope; they are production-hardening phases, not oversights:

| Phase | Not built here |
|---|---|
| **Identity (SSO)** | No SSO / SAML / OIDC, no Microsoft Entra ID integration, no MFA. No password reset, user registration, or user-management UI — only the two seeded users. Production would replace `auth.py`'s login with Entra ID OIDC and map groups to roles; `current_user` / `require_admin` stay as the interface. |
| **Database** | No production database (no Postgres) and no migrations framework. SQLite with `CREATE TABLE IF NOT EXISTS` is enough to prove the pattern; production would move to Postgres with migrations. |
| **Hosting / deploy** | No hosting, deployment pipeline, Docker, or cloud configuration beyond the local run command. |
| **IDV / screening provider** | No real IDV / sanctions-screening provider integration — checks are simulated in-app; production wires the External checks panel to the provider's API and stores its reference. |
| **Flag evaluation** | No per-user rollout bucketing and no flag evaluation API/SDK for other services — in production, product services evaluate flags via that API; here, pages read the flag table directly. |
| **Connectors** | No external connectors or APIs: no email sending, no payment processing (refunds are status changes only), no identity-verification service. No file uploads. |
| **Compliance review** | No security review, CSRF protection, audit-log immutability/retention controls, data-retention policy, or access reviews — all required before handling real customer data. |
| **Client architecture** | No JavaScript framework, no API-only backend, no mobile app. Server-rendered HTML is the deliberate choice for internal tools. |

## 7. How Devin was used

### Session notes (to be completed by the developer)

- How the task was decomposed:
- Where Devin was fast:
- Where Devin needed correction:

## 8. Time log

| Phase | Time |
|---|---|
| Research | ___ |
| Build (this session) | ___ |
| Review/fixes | ___ |

## 9. Tests

```bash
source .venv/bin/activate   # created by ./run.sh, or use your own environment
pytest
```

Each test runs against a fresh temporary SQLite file (via `APP_DB_PATH`) using FastAPI's `TestClient`, so tests never read or modify `app.db`. `tests/test_audit_and_roles.py` covers:

1. A reviewer approving a KYC case creates exactly one audit entry for that case with before `pending`, after `approved`, and the reviewer's email as actor.
2. Approving, and separately marking paid, a refund each create exactly one audit entry with correct before/after statuses.
3. A reviewer POSTing a flag update gets 403, the flag row is unchanged, and no audit entry is written.
4. An admin toggling a flag succeeds and creates exactly one audit entry recording before/after enabled state and rollout.
5. An unauthenticated request to `/kyc` redirects to `/login`.
6. Running (simulated) checks on a case with a Not run check sets it to Clear, sets `checks_last_run_at`, and writes exactly one `checks_run` audit entry.
7. A check seeded as Review is still Review after running checks.
8. Approving a case with a Not run check is refused (400, status unchanged, no decision audit entry, error message shown); approving the same case after running checks succeeds.

9. With `new_checkout_flow` ON, `/preview` shows New checkout (not Classic); after an admin turns it OFF, it shows Classic checkout.
10. With `refund_self_service` OFF, `POST /refunds/new` returns 403 and creates nothing; after an admin turns it ON, the same POST creates a pending refund and exactly one `created` audit entry.
11. Turning `dark_mode_dashboard` ON makes pages render with `<body class="dark">`; OFF removes it.

Extra checks: `/preview` requires login; the flags page shows a Controls line for all seven flags, including the "not wired" one; Reject is allowed while checks are incomplete; the audit CSV is admin-only and has a header row; the home-page banner follows the `homepage_announcement` flag; out-of-range rollout values are rejected without an audit entry; a bad login re-renders the form with an error.
