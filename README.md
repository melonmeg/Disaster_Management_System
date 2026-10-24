# Emergency Response Management System — backend & MySQL

FastAPI + MySQL 8 backend. The MongoDB collections and the Next.js frontend are maintained separately (teammate).

* [docs/API.md](docs/API.md): endpoint contract, roles, error format, MongoDB/Next.js integration
* [docs/DATABASE.md](docs/DATABASE.md): SQL files, advanced SQL, triggers/procedures, MySQL roles, viva commands

```
emergency_response.sql, emergency_response_demo_data.sql   original schema + sample data (unchanged)
sql/00..06_*.sql      base tables, constraints, functions, views, procedures, triggers, roles
sql/07..09_*.sql      viva demo scripts
backend/app/          FastAPI application (routers/ per resource)
backend/scripts/      setup_db.py, create_test_db.py, sqlrunner.py
backend/tests/        pytest integration tests (run against a separate *_test database)
```

## Setup (Windows, Python 3.11+, MySQL 8.0)

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env        # then edit: MYSQL_ADMIN_PASSWORD, DB_*_PASSWORD, JWT_SECRET, SEED_*_PASSWORD
.venv\Scripts\python scripts\setup_db.py --bootstrap
```

`setup_db.py --bootstrap` creates `emergency_response_management` with the original schema and sample data if it does not exist yet. It then applies `sql/01`–`06`, creates the four least-privilege MySQL accounts, and seeds three app logins (bcrypt-hashed):

| Login | Role | Linked responder |
|---|---|---|
| `SEED_ADMIN_USERNAME` (admin) | admin | – |
| `SEED_DISPATCHER_USERNAME` (aarav) | dispatcher | 1 Aarav Sharma |
| `SEED_RESPONDER_USERNAME` (diya) | responder | 2 Diya Nair, Police Unit 12 |

Passwords are the `SEED_*_PASSWORD` values in `backend/.env`. Re-running `setup_db.py` without `--bootstrap` is safe: it never deletes or rewrites rows.

## Run

```powershell
cd backend
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000/docs, call `POST /api/auth/login`, then click **Authorize** and paste the `access_token`.

## Tests

```powershell
cd backend
.venv\Scripts\python -m pytest
```

The suite drops and rebuilds `TEST_DB_NAME` (`emergency_response_management_test`) from the same SQL files on every run. The real database is never touched: the script refuses any name that doesn't end in `_test` or that matches `DB_NAME`. The 53 tests cover:

* auth: login, bad credentials, refresh, logout revocation, deactivation, bcrypt storage
* RBAC: API 403s per role, and MySQL privilege denials per account (errors 1142/1143/1370)
* business rules: dispatch lifecycle, busy units, state machine, stock and over-allocation, returns, resolve rules, composite patient key, transactional call + incident rollback, cross-organization assignment, FK in-use deletes, filters and pagination
* the three demo SQL scripts run end to end, including the deliberate failures

## Final demo checklist

1. `setup_db.py` output, then `SHOW GRANTS FOR erm_role_responder;`
2. Workbench: run `sql/07_queries_demo.sql` section by section (joins → subqueries → aggregates → CTE → recursive).
3. `sql/08_transactions_demo.sql`: COMMIT, ROLLBACK, SAVEPOINT, procedure refusing over-allocation, triggers.
4. Log in as `erm_responder` in the MySQL CLI and show `DELETE FROM incidents ...` failing with ERROR 1142.
5. Swagger UI: log in as the dispatcher → create incident → `GET /units?available=true` → dispatch → allocate resources → over-allocate (409) → status changes → return → resolve.
6. Log in as the responder: `POST /incidents` → 403; update own dispatch status → 200.
7. `pytest` → all green.
