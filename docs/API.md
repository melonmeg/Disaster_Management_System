# Backend API contract

Base URL: `http://localhost:8000/api` · Interactive docs (OpenAPI): `http://localhost:8000/docs`

## Conventions

| Topic | Rule |
|---|---|
| Auth | `Authorization: Bearer <access_token>` on every route except `/auth/login`, `/auth/refresh`, `/health` |
| Roles | `admin`, `dispatcher`, `responder` (string in `user.role`) |
| IDs | MySQL integer primary keys (`incident_id`, `call_id`, `dispatch_id`, `unit_id`, `responder_id`, `resource_id`, `organization_id`). Patients are identified by `(incident_id, patient_no)`. |
| Dates | ISO 8601 without timezone, server local time (`2026-10-12T07:45:00`) |
| Lists | `{"data": [...], "pagination": {"page", "page_size", "total", "total_pages"}}`; query params `page` (≥1), `page_size` (1–100, default 20). Small nested lists return `{"data": [...]}` only. |
| Single record | the object itself |
| PATCH | send only the fields to change |
| Unknown fields | rejected (422) |

### Errors

Every error has the same shape:

```json
{ "error": { "code": "BUSINESS_RULE_VIOLATION", "message": "Insufficient stock: requested 50, available 4", "details": null } }
```

| HTTP | code | When |
|---|---|---|
| 400 | `VALIDATION_ERROR`, `INVALID_REFERENCE`, `CONSTRAINT_VIOLATION` | bad value, referenced id missing, CHECK constraint |
| 401 | `UNAUTHORIZED`, `INVALID_CREDENTIALS` | missing/expired/revoked token, bad login |
| 403 | `FORBIDDEN` | role not allowed (API check) |
| 403 | `DB_PERMISSION_DENIED` | MySQL privileges refused the statement (second layer) |
| 404 | `NOT_FOUND` | record does not exist |
| 409 | `BUSINESS_RULE_VIOLATION`, `INVALID_TRANSITION`, `DUPLICATE`, `IN_USE` | rule from a trigger/procedure, bad status change (`details.allowed` lists valid next states), unique clash, FK still referenced |
| 422 | `VALIDATION_ERROR` | body/query schema error; `details: [{"field", "message"}]` |
| 503 | `DATABASE_UNAVAILABLE` | MySQL down |

## Authentication

| Method & path | Roles | Body | Response |
|---|---|---|---|
| `POST /auth/login` | public | `{username, password}` | `{access_token, refresh_token, token_type:"bearer", expires_in, user:{user_id, username, role, responder_id}}` |
| `POST /auth/refresh` | public | `{refresh_token}` | same as login |
| `POST /auth/logout` | any | – | 204; all of the user's tokens stop working |
| `GET /auth/me` | any | – | `{user_id, username, role, responder_id}` |
| `POST /auth/register` | admin | `{username, password(≥8), role, responder_id?}` (`responder_id` required for responder) | 201 user (no hash) |
| `GET /users` | admin | – | `{data:[user]}` |
| `PATCH /users/{id}` | admin | `{role?, responder_id?, is_active?, password?}` | user; ends that user's sessions |

Access tokens last `ACCESS_TOKEN_MINUTES` (30), refresh tokens `REFRESH_TOKEN_DAYS` (7). On 401 call `/auth/refresh`; if that fails, send the user to login.

## Resources by area

Roles: **A** admin · **D** dispatcher · **R** responder. "R (own)" = only for the responder's own record / unit / incidents their unit was dispatched to.

### Organizations
| | Roles | Notes |
|---|---|---|
| `GET /organizations?status=` | A D R | includes `unit_count`, `resource_count` |
| `GET /organizations/{id}` | A D R | |
| `POST /organizations` | A | `{organization_name, location?, status?: ACTIVE\|INACTIVE}` |
| `PATCH /organizations/{id}` | A | |
| `DELETE /organizations/{id}` | A | 409 `IN_USE` if units/resources/responders reference it |

### Responders
| | Roles | Notes |
|---|---|---|
| `GET /responders?organization_id=&unit_id=&availability=&responder_type=` | A D R | `{responder_id, full_name, responder_type, availability, phone, organization_id, organization_name, unit_id, unit_name, email*}` (*not for R) |
| `GET /responders/{id}` | A D R | |
| `POST /responders` | A | `{first_name, middle_name?, last_name, phone?, email?, responder_type?, availability?, organization_id, unit_id?}` |
| `PATCH /responders/{id}` | A | personal fields / organization |
| `PUT /responders/{id}/unit` | A D | `{unit_id: int \| null}` assign / reassign / unassign; unit must belong to the same organization (409) |
| `PATCH /responders/{id}/availability` | A D, R (own) | `{availability: AVAILABLE\|ON_DUTY\|OFF_DUTY}` |
| `GET /units/{id}/responders` | A D R | crew of a unit |

### Units
| | Roles | Notes |
|---|---|---|
| `GET /units?status=&organization_id=&unit_type=&available=true` | A D R | `{unit_id, unit_name, unit_type, status, base_location, organization_id, organization_name, active_dispatch_count, is_free, crew_size, current_incident_id}`; `available=true` → can be dispatched now |
| `GET /units/{id}` | A D R | plus `active_dispatches: [...]` |
| `GET /units/{id}/dispatches` | A D R | dispatch history (paginated) |
| `POST /units` | A | `{unit_name, unit_type?, status?: AVAILABLE\|OUT_OF_SERVICE, base_location?, organization_id}` |
| `PATCH /units/{id}` | A | same fields; `DISPATCHED` status is managed by the database |

### Incidents
| | Roles | Notes |
|---|---|---|
| `GET /incidents?status=&severity=&location=&incident_type=&unresolved=&created_from=&created_to=&sort=newest\|oldest\|severity` | A D R | `status`/`severity` repeatable; `location` substring. Row: `{incident_id, incident_type, severity, location, status, created_at, resolved_at, call_count, dispatch_count, active_dispatch_count, patient_count, response_minutes, open_minutes}` |
| `GET /incidents/{id}` | A D R | row + `dispatches[]` + `patients[]` |
| `GET /incidents/{id}/dispatches` | A D R | with unit, organization, `crew`, `resources_outstanding` |
| `GET /incidents/{id}/calls` | A D | |
| `GET /incidents/{id}/activity` | A D R | activity log, oldest first |
| `POST /incidents` | A D | `{incident_type, severity: LOW\|MEDIUM\|HIGH\|CRITICAL, location}` → status `OPEN` |
| `PATCH /incidents/{id}` | A D | `{incident_type?, severity?, location?, status?}`; transitions OPEN→IN_PROGRESS/RESOLVED, IN_PROGRESS→RESOLVED, RESOLVED→CLOSED/IN_PROGRESS |
| `POST /incidents/{id}/resolve` | A D | 409 unless all dispatches are finished and all resources returned; sets `resolved_at` |

### Patients (composite key)
| | Roles | Notes |
|---|---|---|
| `GET /incidents/{id}/patients` | A D R | |
| `GET /incidents/{id}/patients/{patient_no}` | A D R | |
| `POST /incidents/{id}/patients` | A D, R (own) | `{patient_name?, age?(0–130), gender?, patient_condition?}`; `patient_no` assigned automatically |
| `PATCH /incidents/{id}/patients/{patient_no}` | A D, R (own) | |
| `DELETE /incidents/{id}/patients/{patient_no}` | A | |

### Dispatches
| | Roles | Notes |
|---|---|---|
| `GET /dispatches?status=&incident_id=&unit_id=&active=` | A D R | history, newest first |
| `GET /dispatches/{id}` | A D R | plus `resources[]` (`quantity_assigned`, `quantity_returned`, `quantity_outstanding`) |
| `POST /dispatches` | A D | `{incident_id, unit_id}` → 201; 404 unknown incident/unit; 409 unit busy/out of service or incident resolved |
| `PATCH /dispatches/{id}/status` | A D, R (own unit) | `{status}`; DISPATCHED→EN_ROUTE/ON_SCENE/CANCELLED, EN_ROUTE→ON_SCENE/CANCELLED, ON_SCENE→COMPLETED |
| `GET /dispatches/{id}/resources` | A D R | |
| `POST /dispatches/{id}/resources` | A D | `{resource_id, quantity}` → 201 dispatch; 409 insufficient stock / dispatch finished |
| `POST /dispatches/{id}/resources/{resource_id}/return` | A D, R (own unit) | `{quantity}`; 409 if more than outstanding |

### Resources
| | Roles | Notes |
|---|---|---|
| `GET /resources?resource_type=&organization_id=&status=&available=` | A D R | `{..., quantity_total, quantity_available, quantity_in_field, utilisation_pct}` |
| `GET /resources/{id}` | A D R | plus `allocations[]` still outstanding |
| `POST /resources` | A | `{resource_name, resource_type?, quantity_total, location?, organization_id}` |
| `PATCH /resources/{id}` | A | `{resource_name?, resource_type?, location?, status?: AVAILABLE\|UNAVAILABLE}` |
| `POST /resources/{id}/restock` | A | `{quantity}` adds to total and available |

### Calls (MySQL `calls` table)
| | Roles | Notes |
|---|---|---|
| `GET /calls?incident_id=&status=&priority=&received_from=&received_to=` | A D | includes `received_by_name` |
| `GET /calls/{id}` | A D | |
| `POST /calls` | A D | `{incident_id}` **or** `{incident: {incident_type, severity, location}}` (creates both in one transaction), plus `caller_name?, caller_phone?, location?, priority?, transcript?, received_by?` (defaults to the dispatcher's responder_id) |
| `PATCH /calls/{id}` | A D | `{status?: RECEIVED\|PROCESSED\|CLOSED, priority?, transcript?}` |

### Activity logs, reports, integration
| | Roles | Notes |
|---|---|---|
| `GET /activity-logs?incident_id=&since=&until=` | A D R | newest first; written automatically by triggers |
| `POST /activity-logs` | A D, R (own) | `{incident_id, action(≤100)}` manual note, prefixed with the username |
| `GET /reports/summary` | A D | incidents by status/severity, response times, unit usage, dispatch counts, low stock, multi-patient incidents |
| `POST /integration/validate-refs` | A D R | `{incident_ids?, call_ids?, dispatch_ids?, unit_ids?, responder_ids?}` → `{valid, missing:{...}}` (R may not check `call_ids`) |
| `GET /health` | public | `{status, database}` |

## Integration with the MongoDB / Next.js side (to confirm with teammate)

1. **Source of truth.** Structured, relational data (incidents, calls, dispatches, units, responders, resources, patients, activity log entries) lives in MySQL and is read and written only through this API. MongoDB holds the flexible or unstructured data, for example full call transcripts or recordings metadata, free-form field reports, and rich timelines.
2. **Linking.** Every MongoDB document that belongs to a MySQL record stores the MySQL integer id under the same field name: `incident_id`, `call_id`, `dispatch_id`, `unit_id`, `responder_id`. Patients use both `incident_id` and `patient_no`. The backend never stores Mongo `_id`s.
3. **Reference checks.** MySQL cannot enforce foreign keys into MongoDB. Before inserting or updating a Mongo document, the Next.js server calls `POST /api/integration/validate-refs` with the ids. If `valid` is false, it does not write and returns 400 to the UI.
4. **Calls and activity logs in the UI.** The call list and details come from `GET /api/calls` and `GET /api/calls/{id}`; the incident timeline comes from `GET /api/incidents/{id}/activity`. Extra Mongo data, such as a transcript document, is fetched from the teammate's own Next.js API route by `call_id` and merged on the frontend.
5. **Authentication.** The frontend stores the access token in memory and the refresh token in an httpOnly cookie, then forwards `Authorization: Bearer` to this API. Hiding buttons by role is UX only; every rule is enforced again here and in MySQL.
6. **Cross-database failures.** Write MySQL first through the API. If the follow-up Mongo write fails, the MySQL record still stands. The frontend shows a warning and retries the Mongo write, which is idempotent because it is keyed by the MySQL id. Mongo documents whose ids `validate-refs` reports missing are orphans and can be cleaned up.
7. **CORS.** Allowed origins come from `CORS_ORIGINS` in `.env`; the default is `http://localhost:3000`.
