"""Request bodies. Field limits mirror the column sizes / CHECK constraints in MySQL."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

Role = Literal["admin", "dispatcher", "responder"]
Severity = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
IncidentStatus = Literal["OPEN", "IN_PROGRESS", "RESOLVED", "CLOSED"]
DispatchStatus = Literal["DISPATCHED", "EN_ROUTE", "ON_SCENE", "COMPLETED", "CANCELLED"]
UnitStatus = Literal["AVAILABLE", "DISPATCHED", "OUT_OF_SERVICE"]
Availability = Literal["AVAILABLE", "ON_DUTY", "OFF_DUTY"]
OrgStatus = Literal["ACTIVE", "INACTIVE"]
ResourceStatus = Literal["AVAILABLE", "DEPLETED", "UNAVAILABLE"]
CallStatus = Literal["RECEIVED", "PROCESSED", "CLOSED"]

Str50 = Field(min_length=1, max_length=50)


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ---------- auth ----------
class LoginIn(Body):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=128)


class RefreshIn(Body):
    refresh_token: str


class RegisterIn(Body):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)
    role: Role
    responder_id: int | None = Field(None, gt=0)


class UserUpdate(Body):
    role: Role | None = None
    responder_id: int | None = Field(None, gt=0)
    is_active: bool | None = None
    password: str | None = Field(None, min_length=8, max_length=128)


# ---------- organizations ----------
class OrganizationIn(Body):
    organization_name: str = Field(min_length=1, max_length=100)
    location: str | None = Field(None, max_length=255)
    status: OrgStatus = "ACTIVE"


class OrganizationUpdate(Body):
    organization_name: str | None = Field(None, min_length=1, max_length=100)
    location: str | None = Field(None, max_length=255)
    status: OrgStatus | None = None


# ---------- responders ----------
class ResponderIn(Body):
    first_name: str = Str50
    middle_name: str | None = Field(None, max_length=50)
    last_name: str = Str50
    phone: str | None = Field(None, max_length=20, pattern=r"^[0-9+\- ]{6,20}$")
    email: EmailStr | None = None
    responder_type: str | None = Field(None, max_length=50)
    availability: Availability = "AVAILABLE"
    organization_id: int = Field(gt=0)
    unit_id: int | None = Field(None, gt=0)


class ResponderUpdate(Body):
    first_name: str | None = Field(None, min_length=1, max_length=50)
    middle_name: str | None = Field(None, max_length=50)
    last_name: str | None = Field(None, min_length=1, max_length=50)
    phone: str | None = Field(None, max_length=20, pattern=r"^[0-9+\- ]{6,20}$")
    email: EmailStr | None = None
    responder_type: str | None = Field(None, max_length=50)
    organization_id: int | None = Field(None, gt=0)


class AssignUnitIn(Body):
    unit_id: int | None = Field(..., gt=0, description="null to unassign")


class AvailabilityIn(Body):
    availability: Availability


# ---------- units ----------
class UnitIn(Body):
    unit_name: str = Field(min_length=1, max_length=100)
    unit_type: str | None = Field(None, max_length=50)
    status: Literal["AVAILABLE", "OUT_OF_SERVICE"] = "AVAILABLE"
    base_location: str | None = Field(None, max_length=255)
    organization_id: int = Field(gt=0)


class UnitUpdate(Body):
    unit_name: str | None = Field(None, min_length=1, max_length=100)
    unit_type: str | None = Field(None, max_length=50)
    status: Literal["AVAILABLE", "OUT_OF_SERVICE"] | None = None
    base_location: str | None = Field(None, max_length=255)


# ---------- incidents ----------
class IncidentIn(Body):
    incident_type: str = Str50
    severity: Severity
    location: str = Field(min_length=1, max_length=255)


class IncidentUpdate(Body):
    incident_type: str | None = Field(None, min_length=1, max_length=50)
    severity: Severity | None = None
    location: str | None = Field(None, min_length=1, max_length=255)
    status: IncidentStatus | None = None


# ---------- dispatches & resources ----------
class DispatchIn(Body):
    incident_id: int = Field(gt=0)
    unit_id: int = Field(gt=0)


class DispatchStatusIn(Body):
    status: DispatchStatus


class AllocationIn(Body):
    resource_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=10000)


class QuantityIn(Body):
    quantity: int = Field(gt=0, le=10000)


class ResourceIn(Body):
    resource_name: str = Field(min_length=1, max_length=100)
    resource_type: str | None = Field(None, max_length=50)
    quantity_total: int = Field(ge=0, le=1_000_000)
    location: str | None = Field(None, max_length=255)
    organization_id: int = Field(gt=0)


class ResourceUpdate(Body):
    resource_name: str | None = Field(None, min_length=1, max_length=100)
    resource_type: str | None = Field(None, max_length=50)
    location: str | None = Field(None, max_length=255)
    status: Literal["AVAILABLE", "UNAVAILABLE"] | None = None


# ---------- patients ----------
class PatientIn(Body):
    patient_name: str | None = Field(None, max_length=100)
    age: int | None = Field(None, ge=0, le=130)
    gender: str | None = Field(None, max_length=20)
    patient_condition: str | None = Field(None, max_length=100)


class PatientUpdate(PatientIn):
    pass


# ---------- calls & activity ----------
class NewIncidentForCall(IncidentIn):
    pass


class CallIn(Body):
    incident_id: int | None = Field(None, gt=0, description="existing incident, or send `incident` to create one")
    incident: NewIncidentForCall | None = None
    received_by: int | None = Field(None, gt=0, description="responder_id; defaults to the logged-in dispatcher")
    caller_name: str | None = Field(None, max_length=100)
    caller_phone: str | None = Field(None, max_length=20, pattern=r"^[0-9+\- ]{6,20}$")
    location: str | None = Field(None, max_length=255)
    priority: Severity = "MEDIUM"
    transcript: str | None = Field(None, max_length=100_000)


class CallUpdate(Body):
    status: CallStatus | None = None
    priority: Severity | None = None
    transcript: str | None = Field(None, max_length=100_000)


class ActivityIn(Body):
    incident_id: int = Field(gt=0)
    action: str = Field(min_length=1, max_length=100)


class ValidateRefsIn(Body):
    incident_ids: list[int] = []
    call_ids: list[int] = []
    dispatch_ids: list[int] = []
    unit_ids: list[int] = []
    responder_ids: list[int] = []
