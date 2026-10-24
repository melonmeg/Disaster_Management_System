-- =====================================================================
-- 02_functions.sql   STORED FUNCTIONS (re-runnable)
-- Small reusable calculations used by views, procedures, triggers and the API.
-- Run against: emergency_response_management
-- =====================================================================

DROP FUNCTION IF EXISTS fn_unit_active_dispatches;
DROP FUNCTION IF EXISTS fn_incident_active_dispatches;
DROP FUNCTION IF EXISTS fn_unit_is_free;
DROP FUNCTION IF EXISTS fn_response_minutes;
DROP FUNCTION IF EXISTS fn_next_patient_no;
DROP FUNCTION IF EXISTS fn_outstanding_quantity;
DROP FUNCTION IF EXISTS fn_responder_full_name;

DELIMITER $$

-- Number of dispatches of a unit that are not finished yet.
CREATE FUNCTION fn_unit_active_dispatches(p_unit_id INT)
RETURNS INT
READS SQL DATA
BEGIN
    DECLARE v_count INT;
    SELECT COUNT(*) INTO v_count
    FROM dispatches
    WHERE unit_id = p_unit_id
      AND status NOT IN ('COMPLETED', 'CANCELLED');
    RETURN v_count;
END$$

-- Number of unfinished dispatches for an incident (an incident with
-- active dispatches cannot be resolved).
CREATE FUNCTION fn_incident_active_dispatches(p_incident_id INT)
RETURNS INT
READS SQL DATA
BEGIN
    DECLARE v_count INT;
    SELECT COUNT(*) INTO v_count
    FROM dispatches
    WHERE incident_id = p_incident_id
      AND status NOT IN ('COMPLETED', 'CANCELLED');
    RETURN v_count;
END$$

-- A unit can be dispatched only if it is not out of service and is not
-- already working on another dispatch.
CREATE FUNCTION fn_unit_is_free(p_unit_id INT)
RETURNS BOOLEAN
READS SQL DATA
BEGIN
    DECLARE v_status VARCHAR(30);
    SELECT status INTO v_status FROM units WHERE unit_id = p_unit_id;
    RETURN v_status IS NOT NULL
       AND v_status <> 'OUT_OF_SERVICE'
       AND fn_unit_active_dispatches(p_unit_id) = 0;
END$$

-- Minutes between incident creation and its first dispatch (NULL if none yet).
CREATE FUNCTION fn_response_minutes(p_incident_id INT)
RETURNS INT
READS SQL DATA
BEGIN
    DECLARE v_minutes INT;
    SELECT TIMESTAMPDIFF(MINUTE, i.created_at, MIN(d.dispatched_at)) INTO v_minutes
    FROM incidents i
    JOIN dispatches d ON d.incident_id = i.incident_id
    WHERE i.incident_id = p_incident_id
    GROUP BY i.incident_id, i.created_at;
    RETURN v_minutes;
END$$

-- Next patient number inside an incident (composite key incident_id + patient_no).
CREATE FUNCTION fn_next_patient_no(p_incident_id INT)
RETURNS INT
READS SQL DATA
BEGIN
    DECLARE v_next INT;
    SELECT COALESCE(MAX(patient_no), 0) + 1 INTO v_next
    FROM incident_patients
    WHERE incident_id = p_incident_id;
    RETURN v_next;
END$$

-- Units of all resources still held by a dispatch (assigned - returned).
CREATE FUNCTION fn_outstanding_quantity(p_dispatch_id INT)
RETURNS INT
READS SQL DATA
BEGIN
    DECLARE v_total INT;
    SELECT COALESCE(SUM(quantity_assigned - quantity_returned), 0) INTO v_total
    FROM dispatch_resources
    WHERE dispatch_id = p_dispatch_id;
    RETURN v_total;
END$$

-- "First M Last" with the optional middle name skipped when NULL.
CREATE FUNCTION fn_responder_full_name(p_responder_id INT)
RETURNS VARCHAR(160)
READS SQL DATA
BEGIN
    DECLARE v_name VARCHAR(160);
    SELECT CONCAT_WS(' ', first_name, middle_name, last_name) INTO v_name
    FROM responders WHERE responder_id = p_responder_id;
    RETURN v_name;
END$$

DELIMITER ;
