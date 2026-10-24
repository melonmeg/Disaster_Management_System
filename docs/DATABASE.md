# MySQL implementation & viva guide

## Files (run order)

| File | Purpose | Re-runnable |
|---|---|---|
| `sql/00_base_tables.sql` | `CREATE DATABASE` + `organizations`, `responders`. `emergency_response.sql` references these tables but never creates them, so they are added here; their columns come from the demo data. | yes (`IF NOT EXISTS`) |
| `emergency_response.sql` | original schema (unchanged) | no |
| `emergency_response_demo_data.sql` | original sample data (unchanged) | no |
| `sql/01_auth_constraints_indexes.sql` | `app_users`, CHECK constraints, UNIQUE (dispatch, resource), indexes | one-time migration |
| `sql/02_functions.sql` | 7 stored functions | yes |
| `sql/03_views.sql` | 5 views | yes |
| `sql/04_procedures.sql` | 6 stored procedures (transactions) | yes |
| `sql/05_triggers.sql` | 18 triggers | yes |
| `sql/06_roles_privileges.sql` | MySQL roles + grants | yes |
| `sql/07_queries_demo.sql` | CRUD, joins, subqueries, aggregates, CTEs, recursive CTEs, window, views, EXPLAIN | demo, read-only |
| `sql/08_transactions_demo.sql` | COMMIT / ROLLBACK / SAVEPOINT, failing procedures, triggers | demo |
| `sql/09_privileges_demo.sql` | SHOW GRANTS, column privileges, per-account tests | demo |

`python scripts/setup_db.py --bootstrap` runs all of the above in order (excluding the demos). It records the one-time migration in `schema_migrations`, so you can re-run it safely.

## Rubric mapping

| Rubric item | Where |
|---|---|
| DDL with constraints | PK/FK in schema, `00`, CHECK + UNIQUE in `01` (status vocabularies, `0 ≤ quantity_available ≤ quantity_total`, `quantity_returned ≤ quantity_assigned`, age range, `resolved_at ≥ created_at`) |
| DML | `07` §A (INSERT/SELECT/UPDATE/DELETE in a rolled-back transaction); API |
| Join queries | `07` §B (4-table join incidents→dispatches→units→responders, LEFT JOIN, resources per incident) |
| Nested / correlated | `07` §C (IN-subquery, correlated COUNT, EXISTS, NOT EXISTS, correlated AVG per organization, derived table) |
| Aggregates / GROUP BY / HAVING | `07` §D; `/api/reports/summary` |
| CTE | `07` §E (unresolved incidents + activity; chained org workload) |
| Recursive | `07` §F1: incidents linked through shared units (graph walk with cycle check); §F2: 15-minute timeline generator |
| Procedures | `sp_create_dispatch`, `sp_allocate_resource`, `sp_return_resource`, `sp_resolve_incident`, `sp_assign_responder`, `sp_incident_report` (multiple result sets) |
| Functions | `fn_unit_is_free`, `fn_unit_active_dispatches`, `fn_incident_active_dispatches`, `fn_response_minutes`, `fn_next_patient_no`, `fn_outstanding_quantity`, `fn_responder_full_name` |
| Triggers | dispatch state machine; unit status sync; stock kept in step with `dispatch_resources`; incident transitions + `resolved_at`; same-organization crew rule; activity logging |
| Transactions | each write procedure: `START TRANSACTION` … `SELECT … FOR UPDATE` … `COMMIT`, `EXIT HANDLER → ROLLBACK; RESIGNAL`; `08` demos; API `POST /calls` with a new incident |
| Views / indexes | `03`; `01` + `07` §I (`EXPLAIN` uses `idx_incidents_status_severity`) |
| Roles + RBAC in database | `06`, `09`, see below |

## Business rules enforced in the database

* A unit can only be dispatched when it is not `OUT_OF_SERVICE` and has no unfinished dispatch. The incident must not be RESOLVED or CLOSED.
* Dispatch status machine: `DISPATCHED → EN_ROUTE | ON_SCENE | CANCELLED`, `EN_ROUTE → ON_SCENE | CANCELLED`, `ON_SCENE → COMPLETED`. A dispatch can't be moved to another incident or unit.
* When a dispatch is inserted, the unit becomes `DISPATCHED` and an OPEN incident becomes `IN_PROGRESS`. When a unit's last active dispatch finishes, the unit becomes `AVAILABLE` again.
* Stock is reduced when resources are allocated and restored when they are returned. Over-allocation, returning more than is outstanding, allocating to finished dispatches, and decreasing assigned or returned quantities are all refused. Status becomes `DEPLETED` at 0.
* An incident can't be resolved while it has active dispatches (trigger) or unreturned resources (procedure). `resolved_at` is set automatically.
* Responders can only join units of their own organization.
* Patients can't be added to CLOSED incidents. `patient_no` is allocated per incident.
* Activity log entries are written automatically for incident creation and status changes, calls, dispatches, allocations and returns, and patients.

Custom errors use `SIGNAL SQLSTATE '45000'` with `MYSQL_ERRNO` 31400, 31404 or 31409. The API maps these to HTTP 400, 404 and 409.

## Access control: two independent layers

**Application layer (FastAPI).** Login checks the bcrypt hash and returns a JWT access token and a refresh token. Every protected route checks the role, and responders are also limited to their own records, unit, and incidents.

**Database layer (MySQL).** The API never uses root. Each request runs on the MySQL account that matches the caller's role:

| App role | MySQL account → role | Can | Cannot |
|---|---|---|---|
| (login) | `erm_auth` → `erm_role_auth` | SELECT/UPDATE `app_users` | read any operational table |
| admin | `erm_admin` → `erm_role_admin` | SELECT/INSERT/UPDATE/DELETE/EXECUTE on the schema | DDL (`DROP`, `ALTER`), `GRANT` |
| dispatcher | `erm_dispatcher` → `erm_role_dispatcher` | manage incidents, calls, dispatches, patients; EXECUTE dispatch/allocation procedures; assign responders (`UPDATE(availability, unit_id)`) | any DELETE; `app_users`; changes to organizations, units and resources master data |
| responder | `erm_responder` → `erm_role_responder` | read operational data; `UPDATE(availability)` on responders; `UPDATE(status)` on dispatches; add/edit patients; `sp_return_resource` | `calls`, `responders.email`, `app_users`, `sp_allocate_resource`, any DELETE |

So even if an API check were missing, MySQL would still refuse the statement (`tests/test_rbac.py::test_mysql_privileges_deny`). Procedures run with `SQL SECURITY DEFINER`, so granting EXECUTE on `sp_allocate_resource` lets a dispatcher change stock **only** through the validated procedure.

## Viva commands

```bash
# MySQL CLI (root)
mysql -u root -p emergency_response_management
SOURCE sql/07_queries_demo.sql;                 -- or run sections in Workbench
mysql --force -u root -p emergency_response_management < sql/08_transactions_demo.sql
mysql -u root -p emergency_response_management < sql/09_privileges_demo.sql

# log in as the restricted accounts (passwords in backend/.env) and try the commands in 09
mysql -u erm_responder -p emergency_response_management
```

Note: demo 1 in `08` commits a new "Gas Leak" incident each time the file is run. Every other change in the demos is rolled back or reversed.
