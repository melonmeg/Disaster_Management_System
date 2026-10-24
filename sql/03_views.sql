-- =====================================================================
-- 03_views.sql   VIEWS (re-runnable)
-- Read models used by the API dashboards and granted to restricted roles.
-- Run against: emergency_response_management
-- =====================================================================

-- One row per incident with its operational counters.
CREATE OR REPLACE VIEW v_incident_overview AS
SELECT
    i.incident_id,
    i.incident_type,
    i.severity,
    i.location,
    i.status,
    i.created_at,
    i.resolved_at,
    (SELECT COUNT(*) FROM calls c WHERE c.incident_id = i.incident_id)             AS call_count,
    (SELECT COUNT(*) FROM dispatches d WHERE d.incident_id = i.incident_id)        AS dispatch_count,
    fn_incident_active_dispatches(i.incident_id)                                    AS active_dispatch_count,
    (SELECT COUNT(*) FROM incident_patients p WHERE p.incident_id = i.incident_id) AS patient_count,
    fn_response_minutes(i.incident_id)                                              AS response_minutes,
    TIMESTAMPDIFF(MINUTE, i.created_at, COALESCE(i.resolved_at, NOW()))             AS open_minutes
FROM incidents i;

-- Current state of every unit: free/busy, crew size and the incident it is working on.
CREATE OR REPLACE VIEW v_unit_availability AS
SELECT
    u.unit_id,
    u.unit_name,
    u.unit_type,
    u.status,
    u.base_location,
    u.organization_id,
    o.organization_name,
    fn_unit_active_dispatches(u.unit_id)                                AS active_dispatch_count,
    fn_unit_is_free(u.unit_id)                                          AS is_free,
    (SELECT COUNT(*) FROM responders r WHERE r.unit_id = u.unit_id)     AS crew_size,
    (SELECT d.incident_id FROM dispatches d
      WHERE d.unit_id = u.unit_id AND d.status NOT IN ('COMPLETED', 'CANCELLED')
      ORDER BY d.dispatched_at DESC LIMIT 1)                            AS current_incident_id
FROM units u
JOIN organizations o ON o.organization_id = u.organization_id;

-- Stock position of each resource including quantities still out in the field.
CREATE OR REPLACE VIEW v_resource_stock AS
SELECT
    r.resource_id,
    r.resource_name,
    r.resource_type,
    r.status,
    r.location,
    r.organization_id,
    o.organization_name,
    r.quantity_total,
    r.quantity_available,
    COALESCE(SUM(dr.quantity_assigned - dr.quantity_returned), 0) AS quantity_in_field,
    ROUND(100 * (r.quantity_total - r.quantity_available) / NULLIF(r.quantity_total, 0), 1)
                                                                  AS utilisation_pct
FROM resources r
JOIN organizations o ON o.organization_id = r.organization_id
LEFT JOIN dispatch_resources dr ON dr.resource_id = r.resource_id
GROUP BY r.resource_id, r.resource_name, r.resource_type, r.status, r.location,
         r.organization_id, o.organization_name, r.quantity_total, r.quantity_available;

-- Dispatches that are still in progress, with incident and unit details.
CREATE OR REPLACE VIEW v_active_dispatches AS
SELECT
    d.dispatch_id,
    d.status AS dispatch_status,
    d.dispatched_at,
    i.incident_id,
    i.incident_type,
    i.severity,
    i.location,
    u.unit_id,
    u.unit_name,
    u.unit_type,
    o.organization_name,
    fn_outstanding_quantity(d.dispatch_id) AS resources_outstanding
FROM dispatches d
JOIN incidents i     ON i.incident_id = d.incident_id
JOIN units u         ON u.unit_id = d.unit_id
JOIN organizations o ON o.organization_id = u.organization_id
WHERE d.status NOT IN ('COMPLETED', 'CANCELLED');

-- Responder directory without e-mail (the responder role only gets this view's columns).
CREATE OR REPLACE VIEW v_responder_directory AS
SELECT
    r.responder_id,
    CONCAT_WS(' ', r.first_name, r.middle_name, r.last_name) AS full_name,
    r.responder_type,
    r.availability,
    r.phone,
    r.organization_id,
    o.organization_name,
    r.unit_id,
    u.unit_name
FROM responders r
JOIN organizations o ON o.organization_id = r.organization_id
LEFT JOIN units u    ON u.unit_id = r.unit_id;
