-- =====================================================================
-- 05_triggers.sql   TRIGGERS (re-runnable)
-- Business rules enforced inside the database so they hold no matter
-- which client writes the data (API, Workbench, MySQL CLI):
--   * dispatch state machine and unit/incident status synchronisation
--   * resource stock kept in step with dispatch_resources
--   * incident status transitions and resolved_at stamping
--   * responders may only join units of their own organization
--   * automatic activity_logs entries
-- Run against: emergency_response_management
-- =====================================================================

DROP TRIGGER IF EXISTS trg_responders_before_insert;
DROP TRIGGER IF EXISTS trg_responders_before_update;
DROP TRIGGER IF EXISTS trg_incidents_after_insert;
DROP TRIGGER IF EXISTS trg_incidents_before_update;
DROP TRIGGER IF EXISTS trg_incidents_after_update;
DROP TRIGGER IF EXISTS trg_calls_after_insert;
DROP TRIGGER IF EXISTS trg_dispatches_before_insert;
DROP TRIGGER IF EXISTS trg_dispatches_after_insert;
DROP TRIGGER IF EXISTS trg_dispatches_before_update;
DROP TRIGGER IF EXISTS trg_dispatches_after_update;
DROP TRIGGER IF EXISTS trg_dispatches_before_delete;
DROP TRIGGER IF EXISTS trg_dispatch_resources_before_insert;
DROP TRIGGER IF EXISTS trg_dispatch_resources_after_insert;
DROP TRIGGER IF EXISTS trg_dispatch_resources_before_update;
DROP TRIGGER IF EXISTS trg_dispatch_resources_after_update;
DROP TRIGGER IF EXISTS trg_dispatch_resources_before_delete;
DROP TRIGGER IF EXISTS trg_patients_before_insert;
DROP TRIGGER IF EXISTS trg_patients_after_insert;

DELIMITER $$

-- ---------------------------------------------------------------------
-- Responders: a responder can only be assigned to a unit of their own organization.
-- ---------------------------------------------------------------------
CREATE TRIGGER trg_responders_before_insert
BEFORE INSERT ON responders
FOR EACH ROW
BEGIN
    IF NEW.unit_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM units WHERE unit_id = NEW.unit_id AND organization_id = NEW.organization_id) THEN
        SIGNAL SQLSTATE '45000' SET MYSQL_ERRNO = 31409,
            MESSAGE_TEXT = 'Responder can only be assigned to a unit of the same organization';
    END IF;
END$$

CREATE TRIGGER trg_responders_before_update
BEFORE UPDATE ON responders
FOR EACH ROW
BEGIN
    IF NEW.unit_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM units WHERE unit_id = NEW.unit_id AND organization_id = NEW.organization_id) THEN
        SIGNAL SQLSTATE '45000' SET MYSQL_ERRNO = 31409,
            MESSAGE_TEXT = 'Responder can only be assigned to a unit of the same organization';
    END IF;
END$$

-- ---------------------------------------------------------------------
-- Incidents
-- ---------------------------------------------------------------------
CREATE TRIGGER trg_incidents_after_insert
AFTER INSERT ON incidents
FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (incident_id, action)
    VALUES (NEW.incident_id, CONCAT('Incident created (', NEW.severity, ' ', NEW.incident_type, ')'));
END$$

-- Allowed transitions:
--   OPEN -> IN_PROGRESS | RESOLVED ; IN_PROGRESS -> RESOLVED
--   RESOLVED -> CLOSED | IN_PROGRESS (re-open) ; CLOSED is final
CREATE TRIGGER trg_incidents_before_update
BEFORE UPDATE ON incidents
FOR EACH ROW
BEGIN
    DECLARE v_message VARCHAR(255);

    IF NEW.status <> OLD.status THEN
        IF NOT (
               (OLD.status = 'OPEN'        AND NEW.status IN ('IN_PROGRESS', 'RESOLVED'))
            OR (OLD.status = 'IN_PROGRESS' AND NEW.status = 'RESOLVED')
            OR (OLD.status = 'RESOLVED'    AND NEW.status IN ('CLOSED', 'IN_PROGRESS'))
        ) THEN
            SET v_message = CONCAT('Invalid incident status change ', OLD.status, ' -> ', NEW.status);
            SIGNAL SQLSTATE '45000' SET MYSQL_ERRNO = 31409, MESSAGE_TEXT = v_message;
        END IF;

        IF NEW.status = 'RESOLVED' THEN
            IF fn_incident_active_dispatches(NEW.incident_id) > 0 THEN
                SIGNAL SQLSTATE '45000' SET MYSQL_ERRNO = 31409,
                    MESSAGE_TEXT = 'Incident still has active dispatches';
            END IF;
            SET NEW.resolved_at = COALESCE(NEW.resolved_at, NOW());
        ELSEIF NEW.status = 'IN_PROGRESS' THEN
            SET NEW.resolved_at = NULL;   -- re-opened
        END IF;
    END IF;
END$$

CREATE TRIGGER trg_incidents_after_update
AFTER UPDATE ON incidents
FOR EACH ROW
BEGIN
    IF NEW.status <> OLD.status THEN
        INSERT INTO activity_logs (incident_id, action)
        VALUES (NEW.incident_id, CONCAT('Incident status ', OLD.status, ' -> ', NEW.status));
    END IF;
END$$

-- ---------------------------------------------------------------------
-- Calls
-- ---------------------------------------------------------------------
CREATE TRIGGER trg_calls_after_insert
AFTER INSERT ON calls
FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (incident_id, action)
    VALUES (NEW.incident_id, CONCAT('Call #', NEW.call_id, ' received'));
END$$

-- ---------------------------------------------------------------------
-- Dispatches
-- ---------------------------------------------------------------------
CREATE TRIGGER trg_dispatches_before_insert
BEFORE INSERT ON dispatches
FOR EACH ROW
BEGIN
    IF EXISTS (SELECT 1 FROM incidents
               WHERE incident_id = NEW.incident_id AND status IN ('RESOLVED', 'CLOSED')) THEN
        SIGNAL SQLSTATE '45000' SET MYSQL_ERRNO = 31409,
            MESSAGE_TEXT = 'Cannot dispatch to a resolved or closed incident';
    END IF;
    IF EXISTS (SELECT 1 FROM units WHERE unit_id = NEW.unit_id) AND NOT fn_unit_is_free(NEW.unit_id) THEN
        SIGNAL SQLSTATE '45000' SET MYSQL_ERRNO = 31409,
            MESSAGE_TEXT = 'Unit is out of service or already on an active dispatch';
    END IF;
    SET NEW.status = COALESCE(NEW.status, 'DISPATCHED');
END$$

CREATE TRIGGER trg_dispatches_after_insert
AFTER INSERT ON dispatches
FOR EACH ROW
BEGIN
    UPDATE units SET status = 'DISPATCHED' WHERE unit_id = NEW.unit_id;
    UPDATE incidents SET status = 'IN_PROGRESS'
    WHERE incident_id = NEW.incident_id AND status = 'OPEN';
    INSERT INTO activity_logs (incident_id, action)
    VALUES (NEW.incident_id,
            CONCAT('Dispatch #', NEW.dispatch_id, ': ',
                   (SELECT unit_name FROM units WHERE unit_id = NEW.unit_id), ' dispatched'));
END$$

-- State machine:
--   DISPATCHED -> EN_ROUTE | ON_SCENE | CANCELLED
--   EN_ROUTE   -> ON_SCENE | CANCELLED
--   ON_SCENE   -> COMPLETED
--   COMPLETED, CANCELLED are final
CREATE TRIGGER trg_dispatches_before_update
BEFORE UPDATE ON dispatches
FOR EACH ROW
BEGIN
    DECLARE v_message VARCHAR(255);

    IF NEW.incident_id <> OLD.incident_id OR NEW.unit_id <> OLD.unit_id THEN
        SIGNAL SQLSTATE '45000' SET MYSQL_ERRNO = 31409,
            MESSAGE_TEXT = 'A dispatch cannot be moved to another incident or unit';
    END IF;

    IF NEW.status <> OLD.status AND NOT (
           (OLD.status = 'DISPATCHED' AND NEW.status IN ('EN_ROUTE', 'ON_SCENE', 'CANCELLED'))
        OR (OLD.status = 'EN_ROUTE'   AND NEW.status IN ('ON_SCENE', 'CANCELLED'))
        OR (OLD.status = 'ON_SCENE'   AND NEW.status = 'COMPLETED')
    ) THEN
        SET v_message = CONCAT('Invalid dispatch status change ', OLD.status, ' -> ', NEW.status);
        SIGNAL SQLSTATE '45000' SET MYSQL_ERRNO = 31409, MESSAGE_TEXT = v_message;
    END IF;
END$$

CREATE TRIGGER trg_dispatches_after_update
AFTER UPDATE ON dispatches
FOR EACH ROW
BEGIN
    IF NEW.status <> OLD.status THEN
        INSERT INTO activity_logs (incident_id, action)
        VALUES (NEW.incident_id, CONCAT('Dispatch #', NEW.dispatch_id, ' ', OLD.status, ' -> ', NEW.status));

        -- Free the unit once its last active dispatch has finished.
        IF NEW.status IN ('COMPLETED', 'CANCELLED') AND fn_unit_active_dispatches(NEW.unit_id) = 0 THEN
            UPDATE units SET status = 'AVAILABLE'
            WHERE unit_id = NEW.unit_id AND status = 'DISPATCHED';
        END IF;
    END IF;
END$$

-- Deleting a dispatch that still holds equipment would lose track of stock.
CREATE TRIGGER trg_dispatches_before_delete
BEFORE DELETE ON dispatches
FOR EACH ROW
BEGIN
    IF fn_outstanding_quantity(OLD.dispatch_id) > 0 THEN
        SIGNAL SQLSTATE '45000' SET MYSQL_ERRNO = 31409,
            MESSAGE_TEXT = 'Dispatch still holds resources; return them first';
    END IF;
END$$

-- ---------------------------------------------------------------------
-- Dispatch resources: keep resources.quantity_available consistent
-- ---------------------------------------------------------------------
CREATE TRIGGER trg_dispatch_resources_before_insert
BEFORE INSERT ON dispatch_resources
FOR EACH ROW
BEGIN
    DECLARE v_available INT;
    DECLARE v_message   VARCHAR(255);

    IF NEW.quantity_assigned IS NULL OR NEW.quantity_assigned <= 0 THEN
        SIGNAL SQLSTATE '45000' SET MYSQL_ERRNO = 31400, MESSAGE_TEXT = 'Quantity must be a positive number';
    END IF;
    SET NEW.quantity_returned = COALESCE(NEW.quantity_returned, 0);

    IF EXISTS (SELECT 1 FROM dispatches
               WHERE dispatch_id = NEW.dispatch_id AND status IN ('COMPLETED', 'CANCELLED')) THEN
        SIGNAL SQLSTATE '45000' SET MYSQL_ERRNO = 31409,
            MESSAGE_TEXT = 'Resources can only be allocated to an active dispatch';
    END IF;

    SELECT quantity_available INTO v_available FROM resources WHERE resource_id = NEW.resource_id;
    IF v_available < NEW.quantity_assigned - NEW.quantity_returned THEN
        SET v_message = CONCAT('Insufficient stock: requested ', NEW.quantity_assigned,
                               ', available ', v_available);
        SIGNAL SQLSTATE '45000' SET MYSQL_ERRNO = 31409, MESSAGE_TEXT = v_message;
    END IF;
END$$

CREATE TRIGGER trg_dispatch_resources_after_insert
AFTER INSERT ON dispatch_resources
FOR EACH ROW
BEGIN
    DECLARE v_delta INT DEFAULT NEW.quantity_assigned - NEW.quantity_returned;

    UPDATE resources
    SET status = CASE WHEN status = 'UNAVAILABLE' THEN status
                      WHEN quantity_available - v_delta = 0 THEN 'DEPLETED'
                      ELSE 'AVAILABLE' END,
        quantity_available = quantity_available - v_delta
    WHERE resource_id = NEW.resource_id;

    INSERT INTO activity_logs (incident_id, action)
    SELECT d.incident_id,
           CONCAT('Allocated ', NEW.quantity_assigned, ' x ', r.resource_name, ' to dispatch #', d.dispatch_id)
    FROM dispatches d JOIN resources r ON r.resource_id = NEW.resource_id
    WHERE d.dispatch_id = NEW.dispatch_id;
END$$

CREATE TRIGGER trg_dispatch_resources_before_update
BEFORE UPDATE ON dispatch_resources
FOR EACH ROW
BEGIN
    DECLARE v_available INT;
    DECLARE v_message   VARCHAR(255);

    IF NEW.dispatch_id <> OLD.dispatch_id OR NEW.resource_id <> OLD.resource_id THEN
        SIGNAL SQLSTATE '45000' SET MYSQL_ERRNO = 31409,
            MESSAGE_TEXT = 'Allocation cannot be moved to another dispatch or resource';
    END IF;
    IF NEW.quantity_assigned < OLD.quantity_assigned OR NEW.quantity_returned < OLD.quantity_returned THEN
        SIGNAL SQLSTATE '45000' SET MYSQL_ERRNO = 31409,
            MESSAGE_TEXT = 'Assigned and returned quantities can only increase';
    END IF;
    IF NEW.quantity_returned > NEW.quantity_assigned THEN
        SIGNAL SQLSTATE '45000' SET MYSQL_ERRNO = 31409,
            MESSAGE_TEXT = 'Returned quantity cannot exceed assigned quantity';
    END IF;

    IF NEW.quantity_assigned > OLD.quantity_assigned THEN
        IF EXISTS (SELECT 1 FROM dispatches
                   WHERE dispatch_id = NEW.dispatch_id AND status IN ('COMPLETED', 'CANCELLED')) THEN
            SIGNAL SQLSTATE '45000' SET MYSQL_ERRNO = 31409,
                MESSAGE_TEXT = 'Resources can only be allocated to an active dispatch';
        END IF;
        SELECT quantity_available INTO v_available FROM resources WHERE resource_id = NEW.resource_id;
        IF v_available < (NEW.quantity_assigned - OLD.quantity_assigned)
                         - (NEW.quantity_returned - OLD.quantity_returned) THEN
            SET v_message = CONCAT('Insufficient stock: requested ', NEW.quantity_assigned - OLD.quantity_assigned,
                                   ', available ', v_available);
            SIGNAL SQLSTATE '45000' SET MYSQL_ERRNO = 31409, MESSAGE_TEXT = v_message;
        END IF;
    END IF;
END$$

CREATE TRIGGER trg_dispatch_resources_after_update
AFTER UPDATE ON dispatch_resources
FOR EACH ROW
BEGIN
    -- positive delta = more stock leaves, negative delta = stock comes back
    DECLARE v_delta INT DEFAULT (NEW.quantity_assigned - OLD.quantity_assigned)
                              - (NEW.quantity_returned - OLD.quantity_returned);

    IF v_delta <> 0 THEN
        UPDATE resources
        SET status = CASE WHEN status = 'UNAVAILABLE' THEN status
                          WHEN quantity_available - v_delta = 0 THEN 'DEPLETED'
                          ELSE 'AVAILABLE' END,
            quantity_available = quantity_available - v_delta
        WHERE resource_id = NEW.resource_id;
    END IF;

    IF NEW.quantity_assigned > OLD.quantity_assigned THEN
        INSERT INTO activity_logs (incident_id, action)
        SELECT d.incident_id,
               CONCAT('Allocated ', NEW.quantity_assigned - OLD.quantity_assigned, ' x ',
                      r.resource_name, ' to dispatch #', d.dispatch_id)
        FROM dispatches d JOIN resources r ON r.resource_id = NEW.resource_id
        WHERE d.dispatch_id = NEW.dispatch_id;
    END IF;
    IF NEW.quantity_returned > OLD.quantity_returned THEN
        INSERT INTO activity_logs (incident_id, action)
        SELECT d.incident_id,
               CONCAT('Returned ', NEW.quantity_returned - OLD.quantity_returned, ' x ',
                      r.resource_name, ' from dispatch #', d.dispatch_id)
        FROM dispatches d JOIN resources r ON r.resource_id = NEW.resource_id
        WHERE d.dispatch_id = NEW.dispatch_id;
    END IF;
END$$

CREATE TRIGGER trg_dispatch_resources_before_delete
BEFORE DELETE ON dispatch_resources
FOR EACH ROW
BEGIN
    IF OLD.quantity_assigned > OLD.quantity_returned THEN
        SIGNAL SQLSTATE '45000' SET MYSQL_ERRNO = 31409,
            MESSAGE_TEXT = 'Allocation still has outstanding quantity; return it first';
    END IF;
END$$

-- ---------------------------------------------------------------------
-- Patients
-- ---------------------------------------------------------------------
CREATE TRIGGER trg_patients_before_insert
BEFORE INSERT ON incident_patients
FOR EACH ROW
BEGIN
    IF EXISTS (SELECT 1 FROM incidents WHERE incident_id = NEW.incident_id AND status = 'CLOSED') THEN
        SIGNAL SQLSTATE '45000' SET MYSQL_ERRNO = 31409,
            MESSAGE_TEXT = 'Cannot add patients to a closed incident';
    END IF;
END$$

CREATE TRIGGER trg_patients_after_insert
AFTER INSERT ON incident_patients
FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (incident_id, action)
    VALUES (NEW.incident_id, CONCAT('Patient #', NEW.patient_no, ' registered'));
END$$

DELIMITER ;
