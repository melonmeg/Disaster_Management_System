"""Emergency Response Management System — backend API.

Run:  uvicorn app.main:app --reload --port 8000     (from the backend/ folder)
Docs: http://localhost:8000/docs  (interactive OpenAPI)
"""
import logging
import time

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware

from . import oplog
from .config import settings
from .db import open_db
from .errors import install_error_handlers
from .routers import (activity, auth, calls, dispatches, incidents, logs, map, organizations, patients, recommendations,
                      resources, responders, units)

logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)   # its request log lines contain URLs (the Mappls key is a query parameter)

app = FastAPI(title="Emergency Response Management API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type"],
)
install_error_handlers(app)


@app.middleware("http")
async def operational_log(request: Request, call_next):
    """Write changes and failures to the MongoDB operational log (best effort, see app/oplog.py)."""
    started = time.perf_counter()
    response = await call_next(request)
    store = oplog.get_oplog()
    if store is not None and oplog.should_log(request.method, request.url.path, response.status_code):
        route = request.scope.get("route")
        entry = oplog.make_entry(method=request.method, path=request.url.path, route="/api" + route.path if route is not None and not route.path.startswith("/api") else getattr(route, "path", None),
                                 status=response.status_code, duration_ms=(time.perf_counter() - started) * 1000,
                                 authorization=request.headers.get("authorization"),
                                 client_ip=request.client.host if request.client else None)
        await run_in_threadpool(store.record, entry)
    return response

for module in (auth, organizations, responders, units, incidents, patients, dispatches, resources, calls, activity,
               map, recommendations, logs):
    app.include_router(module.router, prefix="/api")


@app.get("/api/health", tags=["health"])
def health():
    with open_db("auth") as db:
        db.scalar("SELECT 1 AS ok")
    return {"status": "ok", "database": settings.db_name}
