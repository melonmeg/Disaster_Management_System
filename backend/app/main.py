"""Emergency Response Management System — backend API.

Run:  uvicorn app.main:app --reload --port 8000     (from the backend/ folder)
Docs: http://localhost:8000/docs  (interactive OpenAPI)
"""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import open_db
from .errors import install_error_handlers
from .routers import activity, auth, calls, dispatches, incidents, organizations, patients, resources, responders, units

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Emergency Response Management API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type"],
)
install_error_handlers(app)

for module in (auth, organizations, responders, units, incidents, patients, dispatches, resources, calls, activity):
    app.include_router(module.router, prefix="/api")


@app.get("/api/health", tags=["health"])
def health():
    with open_db("auth") as db:
        db.scalar("SELECT 1 AS ok")
    return {"status": "ok", "database": settings.db_name}
