-- =====================================================================
-- 01_auth_constraints_indexes.sql   (one-time migration, additive only)
-- * app_users table for application login (bcrypt hashes, role column)
-- * CHECK constraints that pin down the status vocabularies and stock rules
-- * Indexes for the most common filters
-- No existing rows are changed or removed; the existing sample data
-- already satisfies every constraint below.
-- Run against: emergency_response_management
-- =====================================================================

-- ---------- Authentication ----------
CREATE TABLE app_users (
    user_id        INT AUTO_INCREMENT PRIMARY KEY,
    username       VARCHAR(50)  NOT NULL,
    password_hash  VARCHAR(255) NOT NULL,          -- bcrypt hash, never plain text
    role           ENUM('admin', 'dispatcher', 'responder') NOT NULL,
    responder_id   INT NULL,                       -- links a login to a responder record
    is_active      BOOLEAN NOT NULL DEFAULT TRUE,
    token_version  INT NOT NULL DEFAULT 0,         -- bumped on logout -> old tokens rejected
    created_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_login_at  DATETIME NULL,

    CONSTRAINT uq_app_users_username  UNIQUE (username),
    CONSTRAINT uq_app_users_responder UNIQUE (responder_id),
    CONSTRAINT fk_app_users_responder FOREIGN KEY (responder_id)
        REFERENCES responders(responder_id),            -- RESTRICT: remove the login first
    -- a 'responder' login must be tied to a responder record
    CONSTRAINT chk_app_users_responder_link
        CHECK (role <> 'responder' OR responder_id IS NOT NULL)
);

-- ---------- Domain constraints (status vocabularies) ----------
ALTER TABLE organizations
    ADD CONSTRAINT chk_org_status CHECK (status IN ('ACTIVE', 'INACTIVE'));

ALTER TABLE responders
    ADD CONSTRAINT chk_responder_availability
        CHECK (availability IN ('AVAILABLE', 'ON_DUTY', 'OFF_DUTY'));

ALTER TABLE units
    ADD CONSTRAINT chk_unit_status
        CHECK (status IN ('AVAILABLE', 'DISPATCHED', 'OUT_OF_SERVICE'));

ALTER TABLE incidents
    ADD CONSTRAINT chk_incident_status
        CHECK (status IN ('OPEN', 'IN_PROGRESS', 'RESOLVED', 'CLOSED')),
    ADD CONSTRAINT chk_incident_severity
        CHECK (severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    ADD CONSTRAINT chk_incident_resolved_after_created
        CHECK (resolved_at IS NULL OR resolved_at >= created_at);

ALTER TABLE calls
    ADD CONSTRAINT chk_call_status   CHECK (status IN ('RECEIVED', 'PROCESSED', 'CLOSED')),
    ADD CONSTRAINT chk_call_priority CHECK (priority IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL'));

ALTER TABLE dispatches
    ADD CONSTRAINT chk_dispatch_status
        CHECK (status IN ('DISPATCHED', 'EN_ROUTE', 'ON_SCENE', 'COMPLETED', 'CANCELLED'));

-- Stock can never go negative or exceed the total owned.
ALTER TABLE resources
    ADD CONSTRAINT chk_resource_status
        CHECK (status IN ('AVAILABLE', 'DEPLETED', 'UNAVAILABLE')),
    ADD CONSTRAINT chk_resource_qty_total CHECK (quantity_total >= 0),
    ADD CONSTRAINT chk_resource_qty_available
        CHECK (quantity_available >= 0 AND quantity_available <= quantity_total);

-- Returned quantity can never exceed what was assigned.
ALTER TABLE dispatch_resources
    ADD CONSTRAINT chk_dr_assigned CHECK (quantity_assigned > 0),
    ADD CONSTRAINT chk_dr_returned
        CHECK (quantity_returned >= 0 AND quantity_returned <= quantity_assigned),
    -- one allocation row per (dispatch, resource); further allocations top it up
    ADD CONSTRAINT uq_dr_dispatch_resource UNIQUE (dispatch_id, resource_id);

ALTER TABLE incident_patients
    ADD CONSTRAINT chk_patient_no  CHECK (patient_no > 0),
    ADD CONSTRAINT chk_patient_age CHECK (age IS NULL OR age BETWEEN 0 AND 130);

-- ---------- Indexes for frequent filters ----------
CREATE INDEX idx_incidents_status_severity ON incidents (status, severity);
CREATE INDEX idx_incidents_created_at      ON incidents (created_at);
CREATE INDEX idx_dispatches_status         ON dispatches (status);
CREATE INDEX idx_dispatches_unit_status    ON dispatches (unit_id, status);
CREATE INDEX idx_units_status              ON units (status);
CREATE INDEX idx_resources_type            ON resources (resource_type);
CREATE INDEX idx_activity_incident_time    ON activity_logs (incident_id, action_time);
CREATE INDEX idx_calls_received_at         ON calls (received_at);
