"""/api/incidents/{incident_id}/patients — composite key (incident_id, patient_no)."""
import pymysql
from fastapi import APIRouter, Depends, Response

from ..common import ensure_responder_on_incident, require_row, updates_from
from ..db import Database
from ..errors import ApiError
from ..schemas import PatientIn, PatientUpdate
from ..security import CurrentUser, current_user, get_db, require_roles

router = APIRouter(prefix="/incidents/{incident_id}/patients", tags=["patients"])


def _incident(db: Database, incident_id: int) -> None:
    require_row(db, "SELECT 1 FROM incidents WHERE incident_id = %s", (incident_id,), "Incident")


def fetch_patient(db: Database, incident_id: int, patient_no: int) -> dict:
    return require_row(db, "SELECT * FROM incident_patients WHERE incident_id = %s AND patient_no = %s",
                       (incident_id, patient_no), "Patient")


@router.get("")
def list_patients(incident_id: int, _: CurrentUser = Depends(current_user), db: Database = Depends(get_db)):
    _incident(db, incident_id)
    return {"data": db.all("SELECT * FROM incident_patients WHERE incident_id = %s ORDER BY patient_no",
                           (incident_id,))}


@router.get("/{patient_no}")
def get_patient(incident_id: int, patient_no: int, _: CurrentUser = Depends(current_user),
                db: Database = Depends(get_db)):
    return fetch_patient(db, incident_id, patient_no)


@router.post("", status_code=201)
def add_patient(incident_id: int, body: PatientIn, user: CurrentUser = Depends(current_user),
                db: Database = Depends(get_db)):
    """patient_no is the next number within the incident (fn_next_patient_no). If two requests race
    for the same number the composite primary key rejects one, and it is retried."""
    _incident(db, incident_id)
    ensure_responder_on_incident(db, user, incident_id)
    for _attempt in range(3):
        patient_no = db.scalar("SELECT fn_next_patient_no(%s) AS n", (incident_id,))
        try:
            db.execute("INSERT INTO incident_patients (incident_id, patient_no, patient_name, age, gender, "
                       "patient_condition) VALUES (%s, %s, %s, %s, %s, %s)",
                       (incident_id, patient_no, body.patient_name, body.age, body.gender, body.patient_condition))
            return fetch_patient(db, incident_id, patient_no)
        except pymysql.IntegrityError as exc:
            if exc.args[0] != 1062:
                raise
    raise ApiError(409, "CONFLICT", "Could not allocate a patient number, please retry")


@router.patch("/{patient_no}")
def update_patient(incident_id: int, patient_no: int, body: PatientUpdate, user: CurrentUser = Depends(current_user),
                   db: Database = Depends(get_db)):
    fetch_patient(db, incident_id, patient_no)
    ensure_responder_on_incident(db, user, incident_id)
    changes = updates_from(body, {"patient_name", "age", "gender", "patient_condition"})
    if changes:
        db.execute(f"UPDATE incident_patients SET {', '.join(f'{k} = %s' for k in changes)} "
                   "WHERE incident_id = %s AND patient_no = %s", [*changes.values(), incident_id, patient_no])
    return fetch_patient(db, incident_id, patient_no)


@router.delete("/{patient_no}", status_code=204, dependencies=[Depends(require_roles("admin"))])
def delete_patient(incident_id: int, patient_no: int, db: Database = Depends(get_db)):
    fetch_patient(db, incident_id, patient_no)
    db.execute("DELETE FROM incident_patients WHERE incident_id = %s AND patient_no = %s", (incident_id, patient_no))
    return Response(status_code=204)
