-- =====================================================================
-- 08_transactions_demo.sql   TRANSACTIONS, COMMIT, ROLLBACK, SAVEPOINT,
--                            TRIGGERS AND PROCEDURES ENFORCING RULES (viva demo)
-- Statements marked "-- EXPECT ERROR" fail on purpose. In the MySQL CLI run:
--   mysql --force -u root -p emergency_response_management < sql/08_transactions_demo.sql
-- Only demo 1 commits (it adds one new incident + call); everything else is rolled back.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. COMMIT: a new emergency call creates an incident and a call atomically
-- ---------------------------------------------------------------------
START TRANSACTION;
INSERT INTO incidents (incident_type, severity, location)
VALUES ('Gas Leak', 'HIGH', '7 Station Road, North District');
SET @new_incident = LAST_INSERT_ID();
INSERT INTO calls (received_by, status, transcript, caller_name, priority, caller_phone, location, incident_id)
VALUES (1, 'RECEIVED', 'Strong smell of gas in the stairwell.', 'Neha Gupta', 'HIGH', '9876511005',
        '7 Station Road, North District', @new_incident);
COMMIT;
SELECT i.incident_id, i.incident_type, c.call_id, c.caller_name
FROM incidents i JOIN calls c ON c.incident_id = i.incident_id
WHERE i.incident_id = @new_incident;

-- ---------------------------------------------------------------------
-- 2. ROLLBACK: a failed step undoes the earlier steps of the transaction
--    The incident insert succeeds, the call references a responder that
--    does not exist (FK error), so the whole unit of work is rolled back.
-- ---------------------------------------------------------------------
SELECT COUNT(*) INTO @before FROM incidents;
START TRANSACTION;
INSERT INTO incidents (incident_type, severity, location) VALUES ('Flooding', 'MEDIUM', 'Underpass, Ring Road');
SET @flood = LAST_INSERT_ID();
-- EXPECT ERROR
INSERT INTO calls (received_by, priority, incident_id) VALUES (999, 'MEDIUM', @flood);
ROLLBACK;
SELECT @before AS incidents_before, COUNT(*) AS incidents_after FROM incidents;   -- equal

-- ---------------------------------------------------------------------
-- 3. SAVEPOINT: keep part of the work, undo the rest
-- ---------------------------------------------------------------------
START TRANSACTION;
INSERT INTO incident_patients (incident_id, patient_no, patient_name, age, gender, patient_condition)
VALUES (102, fn_next_patient_no(102), 'Patient D', 29, 'Male', 'Whiplash');
SAVEPOINT after_first_patient;
INSERT INTO incident_patients (incident_id, patient_no, patient_name, age, gender, patient_condition)
VALUES (102, fn_next_patient_no(102), 'Duplicate entry', 29, 'Male', 'Entered twice by mistake');
ROLLBACK TO SAVEPOINT after_first_patient;
SELECT patient_no, patient_name FROM incident_patients WHERE incident_id = 102;  -- Patient D kept, duplicate gone
ROLLBACK;                                                                         -- demo: undo Patient D too
SELECT patient_no, patient_name FROM incident_patients WHERE incident_id = 102;  -- back to the original 2

-- ---------------------------------------------------------------------
-- 4. Stored procedure transaction: over-allocation is refused and nothing changes
-- ---------------------------------------------------------------------
SELECT resource_id, resource_name, quantity_available FROM resources WHERE resource_id = 204;
-- EXPECT ERROR
CALL sp_allocate_resource(5001, 204, 50);        -- only 4 generators available
SELECT resource_id, resource_name, quantity_available FROM resources WHERE resource_id = 204;   -- still 4

-- EXPECT ERROR
CALL sp_allocate_resource(5004, 201, 1);         -- dispatch 5004 is COMPLETED
-- EXPECT ERROR
CALL sp_return_resource(5001, 203, 10);          -- only 2 extinguishers outstanding

-- Valid allocate + return inside an outer demo transaction (procedures commit
-- their own work, so here we call them and then reverse with a return).
CALL sp_allocate_resource(5002, 202, 2);
SELECT quantity_available AS first_aid_after_allocation FROM resources WHERE resource_id = 202;   -- 10
CALL sp_return_resource(5002, 202, 2);
SELECT quantity_available AS first_aid_after_return FROM resources WHERE resource_id = 202;       -- 12

-- ---------------------------------------------------------------------
-- 5. Triggers enforcing business rules
-- ---------------------------------------------------------------------
-- EXPECT ERROR
UPDATE dispatches SET status = 'COMPLETED' WHERE dispatch_id = 5001;   -- EN_ROUTE -> COMPLETED not allowed
-- EXPECT ERROR
INSERT INTO dispatches (incident_id, unit_id) VALUES (101, 2);         -- unit 2 already busy
-- EXPECT ERROR
INSERT INTO dispatches (incident_id, unit_id) VALUES (103, 4);         -- incident 103 already resolved
-- EXPECT ERROR
UPDATE incidents SET status = 'RESOLVED' WHERE incident_id = 101;      -- still has active dispatches
-- EXPECT ERROR
UPDATE resources SET quantity_available = -1 WHERE resource_id = 201;  -- CHECK constraint
-- EXPECT ERROR
UPDATE responders SET unit_id = 2 WHERE responder_id = 2;              -- police officer onto a fire engine
-- EXPECT ERROR
INSERT INTO incident_patients (incident_id, patient_no, patient_name) VALUES (102, 1, 'Dup'); -- composite PK

-- Trigger side effects inside a rolled-back transaction:
START TRANSACTION;
INSERT INTO dispatches (incident_id, unit_id) VALUES (102, 4);
SET @d = LAST_INSERT_ID();
SELECT unit_id, status FROM units WHERE unit_id = 4;                    -- DISPATCHED (trigger)
UPDATE dispatches SET status = 'ON_SCENE'  WHERE dispatch_id = @d;
UPDATE dispatches SET status = 'COMPLETED' WHERE dispatch_id = @d;
SELECT unit_id, status FROM units WHERE unit_id = 4;                    -- AVAILABLE again (trigger)
SELECT action, action_time FROM activity_logs WHERE incident_id = 102 ORDER BY log_id DESC LIMIT 3;
ROLLBACK;

-- ---------------------------------------------------------------------
-- 6. Row locking (explain in viva; needs two sessions to observe)
--    Session A: START TRANSACTION; SELECT * FROM resources WHERE resource_id = 204 FOR UPDATE;
--    Session B: CALL sp_allocate_resource(5001, 204, 1);   -- waits until A commits/rolls back
-- ---------------------------------------------------------------------
