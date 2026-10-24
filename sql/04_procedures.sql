-- =====================================================================
-- 04_procedures.sql   STORED PROCEDURES (re-runnable)
-- Each write procedure runs in its own transaction: rows are locked with
-- SELECT ... FOR UPDATE, rules are checked, and any error (including one
-- raised by a trigger) rolls the whole transaction back and is re-raised.
--
-- Error convention (SIGNAL SQLSTATE '45000'), mapped to HTTP by the API:
--   MYSQL_ERRNO 31400 = invalid input      -> 400
--   MYSQL_ERRNO 31404 = record not found    -> 404
--   MYSQL_ERRNO 31409 = business-rule clash -> 409
-- Run against: emergency_response_management
-- =====================================================================

DROP PROCEDURE IF EXISTS sp_create_dispatch;
DROP PROCEDURE IF EXISTS sp_allocate_resource;
DROP PROCEDURE IF EXISTS sp_return_resource;
DROP PROCEDURE IF EXISTS sp_resolve_incident;
DROP PROCEDURE IF EXISTS sp_assign_responder;
DROP PROCEDURE IF EXISTS sp_incident_report;

DELIMITER $$

-- ---------------------------------------------------------------------
-- Dispatch a unit to an incident.
-- CALL sp_create_dispatch(102, 4, @id); SELECT @id;
-- ---------------------------------------------------------------------
CREATE PROCEDURE sp_create_dispatch(
    IN  p_incident_id INT,
    IN  p_unit_id     INT,
    OUT p_dispatch_id INT)
BEGIN
    DECLARE v_incident_status VARCHAR(30) DEFAULT NULL;
    DECLARE v_unit_status     VARCHAR(30) DEFAULT NULL;

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    START TRANSACTION;

    SELECT status INTO v_incident_status
    FROM incidents WHERE incident_id = p_incident_id FOR UPDATE;
    IF v_incident_status IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MYSQL_ERRNO = 31404, MESSAGE_TEXT = 'Incident not found';
    END IF;
    IF v_incident_status IN ('RESOLVED', 'CLOSED') THEN
        SIGNAL SQLSTATE '45000' SET MYSQL_ERRNO = 31409,
            MESSAGE_TEXT = 'Cannot dispatch to a resolved or closed incident';
    END IF;

    SELECT status INTO v_unit_status
    FROM units WHERE unit_id = p_unit_id FOR UPDATE;
    IF v_unit_status IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MYSQL_ERRNO = 31404, MESSAGE_TEXT = 'Unit not found';
    END IF;
    IF NOT fn_unit_is_free(p_unit_id) THEN
        SIGNAL SQLSTATE '45000' SET MYSQL_ERRNO = 31409,
            MESSAGE_TEXT = 'Unit is out of service or already on an active dispatch';
    END IF;

    -- trg_dispatches_after_insert marks the unit DISPATCHED, moves the
    -- incident to IN_PROGRESS and writes the activity log.
    INSERT INTO dispatches (incident_id, unit_id) VALUES (p_incident_id, p_unit_id);
    SET p_dispatch_id = LAST_INSERT_ID();

    COMMIT;
END$$

-- ---------------------------------------------------------------------
-- Allocate stock of a resource to an active dispatch.
-- CALL sp_allocate_resource(5003, 202, 2);
-- ---------------------------------------------------------------------
CREATE PROCEDURE sp_allocate_resource(
    IN p_dispatch_id INT,
    IN p_resource_id INT,
    IN p_quantity    INT)
BEGIN
    DECLARE v_dispatch_status VARCHAR(30) DEFAULT NULL;
    DECLARE v_available       INT DEFAULT NULL;
    DECLARE v_resource_status VARCHAR(30);
    DECLARE v_message         VARCHAR(255);

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    IF p_quantity IS NULL OR p_quantity <= 0 THEN
        SIGNAL SQLSTATE '45000' SET MYSQL_ERRNO = 31400, MESSAGE_TEXT = 'Quantity must be a positive number';
    END IF;

    START TRANSACTION;

    SELECT status INTO v_dispatch_status
    FROM dispatches WHERE dispatch_id = p_dispatch_id FOR UPDATE;
    IF v_dispatch_status IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MYSQL_ERRNO = 31404, MESSAGE_TEXT = 'Dispatch not found';
    END IF;
    IF v_dispatch_status IN ('COMPLETED', 'CANCELLED') THEN
        SIGNAL SQLSTATE '45000' SET MYSQL_ERRNO = 31409,
            MESSAGE_TEXT = 'Resources can only be allocated to an active dispatch';
    END IF;

    -- Lock the stock row so two concurrent allocations cannot both succeed.
    SELECT quantity_available, status INTO v_available, v_resource_status
    FROM resources WHERE resource_id = p_resource_id FOR UPDATE;
    IF v_available IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MYSQL_ERRNO = 31404, MESSAGE_TEXT = 'Resource not found';
    END IF;
    IF v_resource_status = 'UNAVAILABLE' THEN
        SIGNAL SQLSTATE '45000' SET MYSQL_ERRNO = 31409, MESSAGE_TEXT = 'Resource is marked unavailable';
    END IF;
    IF v_available < p_quantity THEN
        SET v_message = CONCAT('Insufficient stock: requested ', p_quantity, ', available ', v_available);
        SIGNAL SQLSTATE '45000' SET MYSQL_ERRNO = 31409, MESSAGE_TEXT = v_message;
    END IF;

    -- Stock is decremented and the activity log written by the
    -- dispatch_resources triggers.
    IF EXISTS (SELECT 1 FROM dispatch_resources
               WHERE dispatch_id = p_dispatch_id AND resource_id = p_resource_id) THEN
        UPDATE dispatch_resources
        SET quantity_assigned = quantity_assigned + p_quantity
        WHERE dispatch_id = p_dispatch_id AND resource_id = p_resource_id;
    ELSE
        INSERT INTO dispatch_resources (dispatch_id, resource_id, quantity_assigned, quantity_returned)
        VALUES (p_dispatch_id, p_resource_id, p_quantity, 0);
    END IF;

    COMMIT;
END$$

-- ---------------------------------------------------------------------
-- Record resources coming back from a dispatch.
-- CALL sp_return_resource(5001, 203, 2);
-- ---------------------------------------------------------------------
CREATE PROCEDURE sp_return_resource(
    IN p_dispatch_id INT,
    IN p_resource_id INT,
    IN p_quantity    INT)
BEGIN
    DECLARE v_outstanding INT DEFAULT NULL;
    DECLARE v_message     VARCHAR(255);

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    IF p_quantity IS NULL OR p_quantity <= 0 THEN
        SIGNAL SQLSTATE '45000' SET MYSQL_ERRNO = 31400, MESSAGE_TEXT = 'Quantity must be a positive number';
    END IF;

    START TRANSACTION;

    SELECT quantity_assigned - quantity_returned INTO v_outstanding
    FROM dispatch_resources
    WHERE dispatch_id = p_dispatch_id AND resource_id = p_resource_id
    FOR UPDATE;
    IF v_outstanding IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MYSQL_ERRNO = 31404,
            MESSAGE_TEXT = 'This resource was not allocated to this dispatch';
    END IF;
    IF p_quantity > v_outstanding THEN
        SET v_message = CONCAT('Cannot return ', p_quantity, '; only ', v_outstanding, ' outstanding');
        SIGNAL SQLSTATE '45000' SET MYSQL_ERRNO = 31409, MESSAGE_TEXT = v_message;
    END IF;

    UPDATE dispatch_resources
    SET quantity_returned = quantity_returned + p_quantity
    WHERE dispatch_id = p_dispatch_id AND resource_id = p_resource_id;

    COMMIT;
END$$

-- ---------------------------------------------------------------------
-- Resolve an incident. Allowed only when every dispatch is finished and
-- every allocated resource has been returned.
-- CALL sp_resolve_incident(102);
-- ---------------------------------------------------------------------
CREATE PROCEDURE sp_resolve_incident(IN p_incident_id INT)
BEGIN
    DECLARE v_status      VARCHAR(30) DEFAULT NULL;
    DECLARE v_outstanding INT;

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    START TRANSACTION;

    SELECT status INTO v_status FROM incidents WHERE incident_id = p_incident_id FOR UPDATE;
    IF v_status IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MYSQL_ERRNO = 31404, MESSAGE_TEXT = 'Incident not found';
    END IF;
    IF v_status IN ('RESOLVED', 'CLOSED') THEN
        SIGNAL SQLSTATE '45000' SET MYSQL_ERRNO = 31409, MESSAGE_TEXT = 'Incident is already resolved or closed';
    END IF;
    IF fn_incident_active_dispatches(p_incident_id) > 0 THEN
        SIGNAL SQLSTATE '45000' SET MYSQL_ERRNO = 31409,
            MESSAGE_TEXT = 'Incident still has active dispatches';
    END IF;

    SELECT COALESCE(SUM(dr.quantity_assigned - dr.quantity_returned), 0) INTO v_outstanding
    FROM dispatch_resources dr
    JOIN dispatches d ON d.dispatch_id = dr.dispatch_id
    WHERE d.incident_id = p_incident_id;
    IF v_outstanding > 0 THEN
        SIGNAL SQLSTATE '45000' SET MYSQL_ERRNO = 31409,
            MESSAGE_TEXT = 'Allocated resources must be returned before resolving';
    END IF;

    -- trg_incidents_before_update stamps resolved_at; the after-update trigger logs it.
    UPDATE incidents SET status = 'RESOLVED' WHERE incident_id = p_incident_id;

    COMMIT;
END$$

-- ---------------------------------------------------------------------
-- Assign (or with NULL, unassign) a responder to a unit.
-- CALL sp_assign_responder(1, 1);
-- ---------------------------------------------------------------------
CREATE PROCEDURE sp_assign_responder(IN p_responder_id INT, IN p_unit_id INT)
BEGIN
    DECLARE v_found INT DEFAULT 0;

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    START TRANSACTION;

    SELECT COUNT(*) INTO v_found FROM responders WHERE responder_id = p_responder_id FOR UPDATE;
    IF v_found = 0 THEN
        SIGNAL SQLSTATE '45000' SET MYSQL_ERRNO = 31404, MESSAGE_TEXT = 'Responder not found';
    END IF;
    IF p_unit_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM units WHERE unit_id = p_unit_id) THEN
        SIGNAL SQLSTATE '45000' SET MYSQL_ERRNO = 31404, MESSAGE_TEXT = 'Unit not found';
    END IF;

    -- trg_responders_before_update checks the unit belongs to the same organization.
    UPDATE responders SET unit_id = p_unit_id WHERE responder_id = p_responder_id;

    COMMIT;
END$$

-- ---------------------------------------------------------------------
-- Full incident report: returns four result sets.
-- CALL sp_incident_report(101);
-- ---------------------------------------------------------------------
CREATE PROCEDURE sp_incident_report(IN p_incident_id INT)
READS SQL DATA
BEGIN
    IF NOT EXISTS (SELECT 1 FROM incidents WHERE incident_id = p_incident_id) THEN
        SIGNAL SQLSTATE '45000' SET MYSQL_ERRNO = 31404, MESSAGE_TEXT = 'Incident not found';
    END IF;

    -- 1. Incident summary
    SELECT * FROM v_incident_overview WHERE incident_id = p_incident_id;

    -- 2. Dispatched units with their crews
    SELECT d.dispatch_id, d.status AS dispatch_status, d.dispatched_at,
           u.unit_name, u.unit_type,
           GROUP_CONCAT(CONCAT_WS(' ', r.first_name, r.last_name) ORDER BY r.responder_id SEPARATOR ', ') AS crew
    FROM dispatches d
    JOIN units u ON u.unit_id = d.unit_id
    LEFT JOIN responders r ON r.unit_id = u.unit_id
    WHERE d.incident_id = p_incident_id
    GROUP BY d.dispatch_id, d.status, d.dispatched_at, u.unit_name, u.unit_type
    ORDER BY d.dispatched_at;

    -- 3. Resources used
    SELECT d.dispatch_id, res.resource_name, dr.quantity_assigned, dr.quantity_returned,
           dr.quantity_assigned - dr.quantity_returned AS outstanding
    FROM dispatch_resources dr
    JOIN dispatches d  ON d.dispatch_id = dr.dispatch_id
    JOIN resources res ON res.resource_id = dr.resource_id
    WHERE d.incident_id = p_incident_id
    ORDER BY d.dispatch_id, res.resource_name;

    -- 4. Patients
    SELECT patient_no, patient_name, age, gender, patient_condition
    FROM incident_patients WHERE incident_id = p_incident_id ORDER BY patient_no;
END$$

DELIMITER ;
