CREATE TABLE units (
    unit_id INT AUTO_INCREMENT PRIMARY KEY,
    unit_name VARCHAR(100) NOT NULL,
    unit_type VARCHAR(50),
    status VARCHAR(30) DEFAULT 'AVAILABLE',
    base_location VARCHAR(255),
    organization_id INT NOT NULL,

    FOREIGN KEY (organization_id)
        REFERENCES organizations(organization_id)
);

-- Each responder may be assigned to at most one unit at a time.
-- NULL means the responder is not currently assigned to a unit.
ALTER TABLE responders
    ADD COLUMN unit_id INT NULL;

ALTER TABLE responders
    ADD CONSTRAINT fk_responders_unit
    FOREIGN KEY (unit_id)
    REFERENCES units(unit_id)
    ON DELETE SET NULL;

CREATE TABLE incidents (
    incident_id INT AUTO_INCREMENT PRIMARY KEY,
    incident_type VARCHAR(50) NOT NULL,
    severity VARCHAR(30),
    location VARCHAR(255) NOT NULL,
    status VARCHAR(30) DEFAULT 'OPEN',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    resolved_at DATETIME
);

CREATE TABLE calls (
    call_id INT AUTO_INCREMENT PRIMARY KEY,
    received_by INT NOT NULL,
    status VARCHAR(30) DEFAULT 'RECEIVED',
    transcript LONGTEXT,
    received_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    caller_name VARCHAR(100),
    priority VARCHAR(30),
    caller_phone VARCHAR(20),
    location VARCHAR(255),
    incident_id INT NOT NULL,

    FOREIGN KEY (received_by)
        REFERENCES responders(responder_id),

    FOREIGN KEY (incident_id)
        REFERENCES incidents(incident_id)
);

CREATE TABLE dispatches (
    dispatch_id INT AUTO_INCREMENT PRIMARY KEY,
    incident_id INT NOT NULL,
    unit_id INT NOT NULL,
    dispatched_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(30) DEFAULT 'DISPATCHED',

    FOREIGN KEY (incident_id)
        REFERENCES incidents(incident_id)
        ON DELETE CASCADE,

    FOREIGN KEY (unit_id)
        REFERENCES units(unit_id)
);

CREATE TABLE resources (
    resource_id INT AUTO_INCREMENT PRIMARY KEY,
    resource_name VARCHAR(100) NOT NULL,
    status VARCHAR(30) DEFAULT 'AVAILABLE',
    quantity_available INT DEFAULT 0,
    resource_type VARCHAR(50),
    quantity_total INT DEFAULT 0,
    location VARCHAR(255),
    organization_id INT NOT NULL,

    FOREIGN KEY (organization_id)
        REFERENCES organizations(organization_id)
);

CREATE TABLE dispatch_resources (
    dispatch_resource_id INT AUTO_INCREMENT PRIMARY KEY,
    dispatch_id INT NOT NULL,
    resource_id INT NOT NULL,
    quantity_assigned INT NOT NULL DEFAULT 0,
    quantity_returned INT DEFAULT 0,

    FOREIGN KEY (dispatch_id)
        REFERENCES dispatches(dispatch_id)
        ON DELETE CASCADE,

    FOREIGN KEY (resource_id)
        REFERENCES resources(resource_id)
);

CREATE TABLE incident_patients (
    incident_id INT NOT NULL,
    patient_no INT NOT NULL,
    patient_name VARCHAR(100),
    age INT,
    gender VARCHAR(20),
    patient_condition VARCHAR(100),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (incident_id, patient_no),

    FOREIGN KEY (incident_id)
        REFERENCES incidents(incident_id)
        ON DELETE CASCADE
);

CREATE TABLE activity_logs (
    log_id INT AUTO_INCREMENT PRIMARY KEY,
    incident_id INT NOT NULL,
    action VARCHAR(100) NOT NULL,
    action_time DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (incident_id)
        REFERENCES incidents(incident_id)
);
