# Emergency Response Management System — backend & MySQL

FastAPI + MySQL 8 backend, a Next.js dispatcher console, an incident map (Leaflet + OpenStreetMap), and an AI-assisted dispatch recommender whose history is stored in MongoDB.

* [docs/API.md](docs/API.md): endpoint contract, roles, error format, MongoDB/Next.js integration
* [docs/DATABASE.md](docs/DATABASE.md): SQL files, advanced SQL, triggers/procedures, MySQL roles, viva commands

```
emergency_response.sql, emergency_response_demo_data.sql   original schema + sample data (unchanged)
sql/00..06_*.sql      base tables, constraints, functions, views, procedures, triggers, roles
sql/07..09_*.sql      viva demo scripts
sql/11_call_recordings.sql  calls.audio_recording LONGBLOB + metadata (migration)
sql/10_geocoding.sql  geocode cache table (migration); views v_incident_map / v_unit_locations are in 03_views.sql
frontend/             Next.js 15 dispatcher console (App Router, TypeScript, Leaflet)
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

The suite drops and rebuilds `TEST_DB_NAME` (`emergency_response_management_test`) from the same SQL files on every run. The real database is never touched: the script refuses any name that doesn't end in `_test` or that matches `DB_NAME`. The original 53 tests cover:

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

---

## Dispatcher console, map and recommendations

### Architecture

```
Next.js (3000) --HTTP/JWT--> FastAPI (8000) --> MySQL    incidents, units, dispatches, resources (authoritative)
                                   |        --> MongoDB  recommendation_history (rankings, evidence, decisions, feedback)
                                   |--> Mappls geocoding API, results cached in MySQL geocode_cache
                                   '--> Llama API / any OpenAI-compatible LLM (optional) explanation for an already-computed ranking
Leaflet + OpenStreetMap tiles are loaded by the browser.
```

* **Reused unchanged:** all existing tables, procedures, triggers, roles, auth, `/api/*` routes and their tests.
* **Added:** `geocode_cache` table + two views (additive migration `sql/10_geocoding.sql`), `/api/map/*`, `/api/recommendations/*`, the `frontend/` app.
* **Not used:** Neo4j, Redis, a vector database.

### Setup

1. Backend as above, then apply the new migration to an existing database (additive, never deletes rows):
   `cd backend; .venv\Scripts\python scripts\setup_db.py` (applies `sql/10_geocoding.sql` once, re-applies views and grants).
   `pip install -r requirements.txt` now also installs `pymongo` and `mongomock` (tests only).
2. **MongoDB** (nothing to configure for local use):
   * Install MongoDB Community Server with the default options ("Install as a Service" ticked). It then runs in the background on `127.0.0.1:27017`; check with `Get-Service MongoDB` (Status should be `Running`; start it with `Start-Service MongoDB`).
   * No users, passwords or manual database creation are needed. `backend/.env` already defaults to `MONGODB_URI=mongodb://127.0.0.1:27017` and `MONGODB_DB=erms`; the database, the `recommendation_history` collection and its indexes are created on first use.
   * To look inside: install MongoDB Compass (or `mongosh`), connect to `mongodb://127.0.0.1:27017`, open `erms` -> `recommendation_history`.
   * Without MongoDB the app still works; recommendations are returned but marked "not saved", and history/decisions return 503.
3. **Frontend** (Node 20+):
   ```powershell
   cd frontend
   copy .env.local.example .env.local
   npm install
   npm run dev          # http://localhost:3000   (production: npm run build; npm start)
   ```
   `CORS_ORIGINS` in `backend/.env` must contain the frontend origin (default `http://localhost:3000`).

### Environment variables (backend/.env; see `.env.example`)

| Variable | Purpose |
|---|---|
| `MAPPLS_API_KEY` | **Required for geocoding.** Static key from the Mappls console; sent by the backend only, as the `access_token` query parameter |
| `MAPPLS_REGION`, `MAPPLS_GEOCODE_URL`, `GEOCODER_AMBIGUITY_KM` | country code (optional for India), endpoint override, distance above which multiple matches count as ambiguous |
| `MONGODB_URI`, `MONGODB_DB` | MongoDB connection |
| `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_ENABLED` | optional explanation text from any OpenAI-compatible API such as Llama API (`{LLM_BASE_URL}/chat/completions`, bearer key). Take the base URL and model name from your provider's docs; they change. Without them only the deterministic ranking is shown. The key stays on the backend. The request contains incident type/severity/location text and unit names, but no caller or patient data. |
| `RECO_WEIGHTS` | e.g. `capability=0.5,availability=0.2,distance=0.2,resources=0.1` |
| frontend `NEXT_PUBLIC_API_URL` | backend base URL |

### Map and geocoding

* Incidents (`location`) and units (`base_location`) hold free text only, so coordinates come from geocoding. Results are cached in `geocode_cache` keyed by the trimmed text (case-insensitive); the same text is never looked up twice. `incidents`/`units` are not altered.
* Statuses: `RESOLVED`, `AMBIGUOUS` (several far-apart matches; **no** coordinates stored), `NOT_FOUND`, `MANUAL` (coordinates a dispatcher entered). A provider outage is reported and **not** cached, so it is retried later.
* Only the location string is sent to Mappls; no caller name, phone, transcript or patient data. Calls count against your Mappls plan's quota; the backend geocodes only when a dispatcher presses *Resolve pending locations* (max 25 per call) and caches every answer. **Check Mappls' terms on storing geocoding results** before relying on the cache beyond a college demo. Run `python scripts/mappls_probe.py "<address>"` once to verify your key and see the raw response; coordinates are read from `latitude`/`longitude` (or `lat`/`lng`) fields, and a response without them is reported as an error rather than guessed. Matches that only reach city/district/state level are treated as `AMBIGUOUS` and not placed.
* Unresolved incidents are listed under the map ("Not on the map") and never placed at a guessed position. The sample data uses fictional addresses ("18 MG Road, Central District") that a real geocoder will probably not find: use *Set coordinates* (`PUT /api/map/locations`) for the demo.
* The map polls every 30 s, has severity/status/type/time filters, a legend (colour = severity, solid = open, hollow = resolved), OSM attribution, and an accessible list view. Marker clustering is **not** implemented.

### Recommendation logic (`backend/app/recommendation/`)

1. **Facts** from MySQL: incident (+coordinates), `v_unit_availability`, unit base coordinates, `v_resource_stock`, active dispatches.
2. **Eligibility (rules, no AI):** only `OPEN`/`IN_PROGRESS` incidents; exclude units that are busy (`UNIT_BUSY`), out of service, already dispatched to this incident, or whose `unit_type` neither fits nor supports the incident type (`CAPABILITY_MISMATCH`).
3. **Capability** is derived from `unit_type` via the editable table in `rules.py` (the database has no capability model). An incident type with no rule gets `CAPABILITY_UNKNOWN` and confidence `INSUFFICIENT`; unknown is never treated as a match.
4. **Score** = weighted mean of the factors that are actually known: capability (primary 1.0 / supporting 0.5), availability (crew assigned 1.0 / none 0.3), distance (nearest candidate 1.0, others nearest/own distance; only when both incident and unit base are geocoded; straight-line, not travel time), resources (its organisation holds relevant stock). Missing factors are dropped and reported, never filled in. Weights: `RECO_WEIGHTS`. No historical outcomes are used (too little data), and the scoring is **not statistically validated**.
5. **Explanation (optional LLM):** receives only the structured result (no caller or patient data) and must return JSON. Output is rejected if it names a unit that is not a candidate, quotes a number that is not in the supplied facts, or is malformed; the plain ranking is then shown. `sufficient_evidence` is forced to false when confidence is `INSUFFICIENT`/`LOW`.
6. **Confirmation:** the UI only suggests. A dispatch is created when the dispatcher presses *Confirm dispatch* (existing `POST /api/dispatches`, which re-validates), after which the decision is recorded and linked. The LLM never touches MySQL.

MySQL and MongoDB writes are separate operations (no cross-database transaction). If recording the decision fails after a dispatch succeeded, the UI says so; the dispatch stands.

### New API endpoints (bearer token)

| Endpoint | Roles | Notes |
|---|---|---|
| `GET /map/incidents?status=&severity=&incident_type=&created_from=` | A D R | incidents with `latitude/longitude/geocode_status` (`PENDING`, `RESOLVED`, `AMBIGUOUS`, `NOT_FOUND`, `MANUAL`) + `summary` |
| `POST /map/geocode?limit=10` | A D | geocode uncached locations; reports `error` on provider failure |
| `PUT /map/locations` | A D | `{location, latitude, longitude}` manual coordinates |
| `POST /incidents/{id}/recommendations` | A D | generate; `persisted:false` if MongoDB is down |
| `GET /incidents/{id}/recommendations?limit=` | A D | history, newest first |
| `GET /recommendations/summary` | A D | `{pending}` |
| `GET /recommendations/{rid}` | A D | `ranking`, `explanation`, `decision`, `feedback`, `status` (GENERATED / REVIEWED / SUPERSEDED) |
| `POST /recommendations/{rid}/decision` | A D | `{decision: ACCEPTED/REJECTED/OVERRIDDEN, unit_id?, reason?}`; accept needs a candidate, override needs a reason; one decision per recommendation (409) |
| `PUT /recommendations/{rid}/dispatch` | A D | `{dispatch_id}` links the dispatch created after confirmation |
| `POST /recommendations/{rid}/feedback` | A D | `{rating?: 1-5, comment?}` |
| `DELETE /recommendations/{rid}` | A | removes the record (204) |

Responders get 403 on recommendation endpoints and on the geocode/location writes; MySQL also denies them writes to `geocode_cache` (`sql/06`).

### Roles in the console

| | admin | dispatcher | responder |
|---|---|---|---|
| Dashboard, incidents, map, units, resources (read) | yes | yes | yes |
| Create/edit incidents, create dispatches, allocate resources, recommendations | yes | yes | no |
| Update dispatch status / return resources | yes | yes | own unit only |
| Create/edit units and resources, restock | yes | no | no |

Hiding buttons is a convenience; the API and MySQL privileges enforce these rules. Tokens are kept in `sessionStorage` (cleared when the tab closes; readable by scripts on the same origin).

### Tests

```powershell
cd backend; .venv\Scripts\python -m pytest          # 103 tests; needs MySQL, not MongoDB
cd ..\frontend; npm run typecheck; npm run build     # type check + production build
```

The recommendation tests use **mongomock** (an in-memory MongoDB imitation); run the app against a real MongoDB to see real-server behaviour. There are no automated browser tests.

### Demo workflow

1. `setup_db.py`, start MongoDB, backend, `npm run dev`; sign in as the dispatcher.
2. **Map** -> *Resolve pending locations* (or set coordinates for the fictional sample addresses) -> click a marker -> the side panel loads the incident.
3. *Generate recommendation*: ranked units, exclusions with reason codes, missing-information notes and (if configured) the explanation.
4. *Dispatch this unit...* -> *Confirm dispatch* -> the unit turns busy; Dispatches -> Details -> allocate resources (over-allocation is warned in the UI and refused by the server).
5. Regenerate: the dispatched unit is now excluded and the previous recommendation is SUPERSEDED (`db.recommendation_history.find()` in mongosh).
6. Sign in as the responder: no recommendation panel or create buttons; update own dispatch status.

### Call recordings (BLOB) and transcriptions (MongoDB)

* **MySQL BLOB/CLOB:** `calls.audio_recording` is a `LONGBLOB` holding the recorded audio (BLOB); `calls.transcript` is the existing `LONGTEXT` (CLOB). Metadata columns (`audio_mime_type`, `audio_filename`, `audio_size_bytes`, `audio_sha256`, `audio_uploaded_at`) and a CHECK constraint keep them consistent. Added by the additive migration `sql/11_call_recordings.sql` (existing rows get NULL).
* **Why list queries name their columns:** a `SELECT *` would drag megabytes of audio into every call list. The API selects explicit columns plus `has_recording`, and reads the BLOB only on the download endpoint.
* **Limits and checks:** `MAX_RECORDING_MB` (default 25; MySQL's `max_allowed_packet` is 64 MB by default). Accepted types: mp3, wav, ogg, flac, m4a/mp4, webm. The file's first bytes must match its declared type, so an arbitrary file cannot be stored as audio. Admin and dispatcher only; responders get 403.
* **Transcription (Groq Whisper -> MongoDB):** after an upload the console calls `POST /api/calls/{id}/transcribe`. The backend reads the stored audio, sends it to Groq's speech-to-text API (`whisper-large-v3-turbo` by default), and saves the text, language and timestamped segments in MongoDB. **The audio leaves your machine for Groq.** If transcription fails the upload still stands, the console says so, and the **Transcribe** button retries. `PUT /api/calls/{id}/transcription` still accepts a transcript from any other tool. Transcripts are stored in MongoDB (`call_transcripts`, one document per call, unique index on `call_id`). It records the SHA-256 of the audio it was made from, so a transcript of a replaced recording is flagged `matches_current_recording: false`.

| Endpoint | Roles | Notes |
|---|---|---|
| `PUT /calls/{id}/recording?filename=` | A D | raw file as the body, `Content-Type: audio/...`; replaces an existing one; 413 too large, 415 wrong type, 400 content mismatch |
| `GET /calls/{id}/recording` | A D | the audio bytes with its content type |
| `DELETE /calls/{id}/recording` | A | removes the audio only |
| `POST /calls/{id}/transcribe?language=` | A D | transcribe the stored audio with Groq and save it (replaces an older one); 409 no recording, 502/503 provider problem, 422 no speech |
| `PUT /calls/{id}/transcription` | A D | `{text, language?, engine?, segments?: [{start, end, text, speaker?}]}`; create or replace |
| `GET /calls/{id}/transcription` | A D | includes `matches_current_recording` |
| `DELETE /calls/{id}/transcription` | A | |

```python
# example: send a recording, then its transcription (any speech-to-text tool can fill `text`/`segments`)
import httpx
H = {"Authorization": "Bearer <access_token>"}
httpx.put("http://localhost:8000/api/calls/1001/recording", params={"filename": "call.wav"},
          headers={**H, "Content-Type": "audio/wav"}, content=open("call.wav", "rb").read())
httpx.put("http://localhost:8000/api/calls/1001/transcription", headers=H,
          json={"text": "Smoke on the second floor.", "language": "en", "engine": "my-stt-tool",
                "segments": [{"start": 0.0, "end": 2.5, "text": "Smoke on the second floor."}]})
```

The incident page shows each call's recording (upload, play, remove) and its transcription.

### Operational log (MongoDB `operational_logs`)

Every request that **changes data** (anything but GET) and every **failed request** (HTTP 400 and up) is written to MongoDB: time, method, path, route, status, duration, caller id and role (from the token), client IP, request id. Successful reads are skipped (the dashboard polls every 30 s), and request bodies, query strings, passwords and tokens are never stored. Entries expire after `OPLOG_RETENTION_DAYS` (default 90, TTL index). Admins read it with `GET /api/logs` (filters: `user_id`, `method`, `status_min`, `status_max`, `path_prefix`, `since`, `until`) or on the **Operational log** page. It is best effort: if MongoDB is down, entries are dropped (a warning goes to the process log) and the API keeps working. It is separate from MySQL `activity_logs`, the per-incident timeline written by triggers. Recommendation history (`recommendation_history`) is also in MongoDB.

| Variable | Meaning |
|---|---|
| `STT_API_KEY` / `STT_BASE_URL` / `STT_MODEL` / `STT_ENABLED` | Groq speech-to-text (key falls back to `LLM_API_KEY`; default URL `https://api.groq.com/openai/v1`, model `whisper-large-v3-turbo`) |
| `OPLOG_ENABLED` / `OPLOG_RETENTION_DAYS` | operational log on/off and retention |

### Resetting the seed logins

`setup_db.py` creates the `SEED_*` logins only if they do not exist, so changing their passwords in `.env` later has no effect on an existing database. Run `python scripts/setup_db.py --reset-seed-passwords` to set those three logins' passwords to the current `.env` values (it ends their sessions and touches no other user).

### Not implemented / limitations

* Similar/duplicate-incident detection (optional extension) and any vector search: not built. The rubric (`DBMS Level 3.pdf`, images only) asks for "NoSQL/Vector", so MongoDB satisfies it and no vector store was needed. Its NoSQL "RUD" item is covered by read, update (decision/feedback/link) and admin delete of recommendation records. New docs: `docs/ER_DIAGRAM.md` (ER diagram, Mongo document, technology justification). A full rubric audit of the existing SQL work was not redone; it was left as is.
* No road routing or travel time; unit locations are only their geocoded `base_location` text.
* No marker clustering, no automated browser tests, no real-time push (30 s polling).
* The LLM path (OpenAI-compatible request shape) was tested with stubbed replies only, not against a live Llama API; the Mappls client was tested against stubbed responses only, and its response format for coordinates is unverified against a real account.
* `npm audit` reports a postcss advisory bundled with Next 15 (build-time CSS tooling); the fix is a Next 16 upgrade.
