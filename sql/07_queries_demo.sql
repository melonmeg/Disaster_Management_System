-- =====================================================================
-- 07_queries_demo.sql   SQL OPERATIONS & ADVANCED QUERIES (viva demo)
-- Read-only except section A, which runs inside a transaction that is
-- rolled back, so the sample data is left unchanged.
--   mysql -u root -p emergency_response_management < sql/07_queries_demo.sql
-- or open in MySQL Workbench and run section by section.
-- =====================================================================

-- ---------------------------------------------------------------------
-- A. CRUD (DML) — inside a transaction, rolled back at the end
-- ---------------------------------------------------------------------
START TRANSACTION;

-- CREATE
INSERT INTO incidents (incident_type, severity, location)
VALUES ('Gas Leak', 'CRITICAL', '7 Station Road, North District');
SET @demo_incident = LAST_INSERT_ID();

-- READ (trigger trg_incidents_after_insert already wrote an activity log)
SELECT i.*, a.action
FROM incidents i JOIN activity_logs a ON a.incident_id = i.incident_id
WHERE i.incident_id = @demo_incident;

-- UPDATE
UPDATE incidents SET severity = 'HIGH', location = '7 Station Road (rear), North District'
WHERE incident_id = @demo_incident;
SELECT incident_id, severity, location FROM incidents WHERE incident_id = @demo_incident;

-- DELETE (child log rows first: activity_logs references incidents)
DELETE FROM activity_logs WHERE incident_id = @demo_incident;
DELETE FROM incidents     WHERE incident_id = @demo_incident;
SELECT COUNT(*) AS rows_left FROM incidents WHERE incident_id = @demo_incident;

ROLLBACK;

-- ---------------------------------------------------------------------
-- B. JOINS
-- ---------------------------------------------------------------------

-- B1. Incidents by severity, status and location (most severe first)
SELECT incident_id, incident_type, severity, status, location, created_at
FROM incidents
ORDER BY FIELD(severity, 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'), status, location;

-- B2. Units and responders associated with each incident (4-table join)
SELECT i.incident_id, i.incident_type, d.dispatch_id, d.status AS dispatch_status,
       u.unit_name, o.organization_name,
       CONCAT_WS(' ', r.first_name, r.middle_name, r.last_name) AS responder, r.responder_type
FROM incidents i
JOIN dispatches d    ON d.incident_id = i.incident_id
JOIN units u         ON u.unit_id = d.unit_id
JOIN organizations o ON o.organization_id = u.organization_id
LEFT JOIN responders r ON r.unit_id = u.unit_id
ORDER BY i.incident_id, d.dispatch_id;

-- B3. Every unit with its latest dispatch, including units never dispatched (LEFT JOIN)
SELECT u.unit_id, u.unit_name, u.status, d.dispatch_id, d.incident_id, d.status AS dispatch_status
FROM units u
LEFT JOIN dispatches d
       ON d.unit_id = u.unit_id
      AND d.dispatched_at = (SELECT MAX(d2.dispatched_at) FROM dispatches d2 WHERE d2.unit_id = u.unit_id)
ORDER BY u.unit_id;

-- B4. Resources sent to each incident (incident -> dispatch -> allocation -> resource)
SELECT i.incident_id, i.incident_type, res.resource_name,
       SUM(dr.quantity_assigned) AS assigned, SUM(dr.quantity_returned) AS returned
FROM incidents i
JOIN dispatches d          ON d.incident_id = i.incident_id
JOIN dispatch_resources dr ON dr.dispatch_id = d.dispatch_id
JOIN resources res         ON res.resource_id = dr.resource_id
GROUP BY i.incident_id, i.incident_type, res.resource_name
ORDER BY i.incident_id, res.resource_name;

-- ---------------------------------------------------------------------
-- C. NESTED AND CORRELATED SUBQUERIES
-- ---------------------------------------------------------------------

-- C1. Nested: incidents that an ambulance was sent to
SELECT incident_id, incident_type, location
FROM incidents
WHERE incident_id IN (SELECT d.incident_id FROM dispatches d
                      WHERE d.unit_id IN (SELECT unit_id FROM units WHERE unit_type = 'Ambulance'));

-- C2. Correlated: incidents involving more than one patient
SELECT i.incident_id, i.incident_type,
       (SELECT COUNT(*) FROM incident_patients p WHERE p.incident_id = i.incident_id) AS patients
FROM incidents i
WHERE (SELECT COUNT(*) FROM incident_patients p WHERE p.incident_id = i.incident_id) > 1;

-- C3. Correlated EXISTS: responders whose unit is currently on an active dispatch
SELECT r.responder_id, CONCAT_WS(' ', r.first_name, r.last_name) AS responder, r.unit_id
FROM responders r
WHERE EXISTS (SELECT 1 FROM dispatches d
              WHERE d.unit_id = r.unit_id AND d.status NOT IN ('COMPLETED', 'CANCELLED'));

-- C4. NOT EXISTS: available units (no active dispatch, not out of service)
SELECT u.unit_id, u.unit_name, u.unit_type, u.base_location
FROM units u
WHERE u.status <> 'OUT_OF_SERVICE'
  AND NOT EXISTS (SELECT 1 FROM dispatches d
                  WHERE d.unit_id = u.unit_id AND d.status NOT IN ('COMPLETED', 'CANCELLED'));

-- C5. Correlated against the group: resources whose stock ratio is below their organization's average
SELECT r.resource_name, r.organization_id,
       ROUND(r.quantity_available / r.quantity_total, 2) AS stock_ratio
FROM resources r
WHERE r.quantity_available / r.quantity_total <
      (SELECT AVG(r2.quantity_available / r2.quantity_total)
       FROM resources r2 WHERE r2.organization_id = r.organization_id);

-- C6. Derived table: units dispatched more often than the average unit
SELECT u.unit_name, t.dispatches
FROM (SELECT unit_id, COUNT(*) AS dispatches FROM dispatches GROUP BY unit_id) AS t
JOIN units u ON u.unit_id = t.unit_id
WHERE t.dispatches > (SELECT AVG(cnt) FROM (SELECT COUNT(*) AS cnt FROM dispatches GROUP BY unit_id) AS x);

-- ---------------------------------------------------------------------
-- D. AGGREGATES, GROUP BY, HAVING
-- ---------------------------------------------------------------------

-- D1. Dispatch summary per incident
SELECT i.incident_id, i.incident_type,
       COUNT(d.dispatch_id)                                  AS total_dispatches,
       SUM(d.status NOT IN ('COMPLETED', 'CANCELLED'))       AS active_dispatches,
       MIN(d.dispatched_at)                                  AS first_dispatch,
       TIMESTAMPDIFF(MINUTE, i.created_at, MIN(d.dispatched_at)) AS response_minutes
FROM incidents i
LEFT JOIN dispatches d ON d.incident_id = i.incident_id
GROUP BY i.incident_id, i.incident_type, i.created_at;

-- D2. HAVING: incidents that needed more than one unit
SELECT incident_id, COUNT(DISTINCT unit_id) AS units_sent
FROM dispatches
GROUP BY incident_id
HAVING COUNT(DISTINCT unit_id) > 1;

-- D3. HAVING: incidents with multiple patients, with age statistics
SELECT incident_id, COUNT(*) AS patients, MIN(age) AS youngest, MAX(age) AS oldest, ROUND(AVG(age), 1) AS avg_age
FROM incident_patients
GROUP BY incident_id
HAVING COUNT(*) > 1;

-- D4. Resource usage by type
SELECT res.resource_type,
       SUM(res.quantity_total)     AS owned,
       SUM(res.quantity_available) AS on_hand,
       COALESCE(SUM(u.out_now), 0) AS in_field
FROM resources res
LEFT JOIN (SELECT resource_id, SUM(quantity_assigned - quantity_returned) AS out_now
           FROM dispatch_resources GROUP BY resource_id) u ON u.resource_id = res.resource_id
GROUP BY res.resource_type
ORDER BY in_field DESC;

-- D5. Calls received per responder (call-taker workload)
SELECT r.responder_id, CONCAT_WS(' ', r.first_name, r.last_name) AS call_taker,
       COUNT(c.call_id) AS calls, SUM(c.priority = 'HIGH') AS high_priority_calls
FROM responders r
JOIN calls c ON c.received_by = r.responder_id
GROUP BY r.responder_id, r.first_name, r.last_name
HAVING COUNT(c.call_id) >= 1
ORDER BY calls DESC;

-- ---------------------------------------------------------------------
-- E. COMMON TABLE EXPRESSIONS
-- ---------------------------------------------------------------------

-- E1. Unresolved incidents with their response activity
WITH unresolved AS (
    SELECT incident_id, incident_type, severity, created_at
    FROM incidents WHERE status IN ('OPEN', 'IN_PROGRESS')
),
activity AS (
    SELECT incident_id, COUNT(*) AS log_entries, MAX(action_time) AS last_activity
    FROM activity_logs GROUP BY incident_id
),
units_on_it AS (
    SELECT incident_id, COUNT(*) AS active_units
    FROM dispatches WHERE status NOT IN ('COMPLETED', 'CANCELLED') GROUP BY incident_id
)
SELECT u.incident_id, u.incident_type, u.severity,
       COALESCE(o.active_units, 0) AS active_units,
       COALESCE(a.log_entries, 0)  AS log_entries,
       a.last_activity
FROM unresolved u
LEFT JOIN activity a    ON a.incident_id = u.incident_id
LEFT JOIN units_on_it o ON o.incident_id = u.incident_id
ORDER BY FIELD(u.severity, 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW');

-- E2. Workload per organization (chained CTEs)
WITH org_dispatches AS (
    SELECT u.organization_id, COUNT(*) AS dispatches,
           SUM(d.status NOT IN ('COMPLETED', 'CANCELLED')) AS active
    FROM dispatches d JOIN units u ON u.unit_id = d.unit_id
    GROUP BY u.organization_id
),
org_staff AS (
    SELECT organization_id, COUNT(*) AS responders,
           SUM(availability = 'AVAILABLE') AS available_responders
    FROM responders GROUP BY organization_id
)
SELECT o.organization_name,
       COALESCE(s.responders, 0) AS responders,
       COALESCE(s.available_responders, 0) AS available_responders,
       COALESCE(d.dispatches, 0) AS dispatches,
       COALESCE(d.active, 0) AS active_dispatches
FROM organizations o
LEFT JOIN org_staff s      ON s.organization_id = o.organization_id
LEFT JOIN org_dispatches d ON d.organization_id = o.organization_id
ORDER BY active_dispatches DESC;

-- ---------------------------------------------------------------------
-- F. RECURSIVE CTEs
-- ---------------------------------------------------------------------

-- F1. Incidents linked through shared units, starting from incident 101.
--     Ambulance 07 served both 101 and 103, so 103 is reachable from 101.
--     Useful to see which incidents compete for the same crews.
WITH RECURSIVE linked (incident_id, depth, path) AS (
    SELECT 101, 0, CAST('101' AS CHAR(200))
    UNION ALL
    SELECT d2.incident_id, l.depth + 1, CONCAT(l.path, ',', d2.incident_id)
    FROM linked l
    JOIN dispatches d1 ON d1.incident_id = l.incident_id
    JOIN dispatches d2 ON d2.unit_id = d1.unit_id AND d2.incident_id <> d1.incident_id
    WHERE FIND_IN_SET(d2.incident_id, l.path) = 0      -- avoid cycles
      AND l.depth < 10
)
SELECT DISTINCT l.incident_id, l.depth, REPLACE(l.path, ',', ' -> ') AS path, i.incident_type, i.status
FROM linked l JOIN incidents i ON i.incident_id = l.incident_id
ORDER BY l.depth, l.incident_id;

-- F2. 15-minute activity timeline on the morning of 12 Oct 2026, including empty slots
WITH RECURSIVE slots (slot_start) AS (
    SELECT CAST('2026-10-12 07:30:00' AS DATETIME)
    UNION ALL
    SELECT slot_start + INTERVAL 15 MINUTE FROM slots WHERE slot_start < '2026-10-12 08:30:00'
)
SELECT s.slot_start,
       (SELECT COUNT(*) FROM calls c
         WHERE c.received_at >= s.slot_start AND c.received_at < s.slot_start + INTERVAL 15 MINUTE) AS calls,
       (SELECT COUNT(*) FROM dispatches d
         WHERE d.dispatched_at >= s.slot_start AND d.dispatched_at < s.slot_start + INTERVAL 15 MINUTE) AS dispatches
FROM slots s
ORDER BY s.slot_start;

-- ---------------------------------------------------------------------
-- G. WINDOW FUNCTION: rank incidents by response time within each severity
-- ---------------------------------------------------------------------
SELECT incident_id, severity, response_minutes,
       RANK() OVER (PARTITION BY severity ORDER BY response_minutes) AS rank_in_severity
FROM v_incident_overview
WHERE response_minutes IS NOT NULL;

-- ---------------------------------------------------------------------
-- H. VIEWS AND STORED FUNCTIONS
-- ---------------------------------------------------------------------
SELECT * FROM v_incident_overview;
SELECT * FROM v_unit_availability WHERE is_free = TRUE;          -- available units
SELECT * FROM v_resource_stock WHERE quantity_available > 0;     -- available resources
SELECT * FROM v_active_dispatches;
SELECT fn_response_minutes(101)      AS response_minutes_101,
       fn_unit_is_free(4)            AS unit4_free,
       fn_next_patient_no(102)       AS next_patient_102,
       fn_outstanding_quantity(5001) AS outstanding_5001,
       fn_responder_full_name(4)     AS responder_4;

-- Stored procedure returning several result sets
CALL sp_incident_report(101);

-- ---------------------------------------------------------------------
-- I. INDEXES
-- ---------------------------------------------------------------------
SHOW INDEX FROM incidents;
EXPLAIN SELECT incident_id, location FROM incidents WHERE status = 'IN_PROGRESS' AND severity = 'HIGH';
