USE emergency_response_management;

-- Demo data for Emergency Response Management System.
-- Run after creating the schema. Inserts sample rows only.
-- Running this file more than once may cause duplicate primary-key errors.

INSERT INTO organizations
    (organization_id, organization_name, location, status)
VALUES
    (1, 'City Police Department', 'Central District', 'ACTIVE'),
    (2, 'City Fire and Rescue', 'North District', 'ACTIVE'),
    (3, 'Emergency Medical Services', 'South District', 'ACTIVE');

INSERT INTO units
    (unit_id, unit_name, unit_type, status, base_location, organization_id)
VALUES
    (1, 'Police Unit 12', 'Police Car', 'AVAILABLE', 'Central Station', 1),
    (2, 'Fire Engine 04', 'Fire Truck', 'DISPATCHED', 'North Fire Station', 2),
    (3, 'Ambulance 07', 'Ambulance', 'DISPATCHED', 'South Medical Base', 3),
    (4, 'Rescue Unit 02', 'Rescue Vehicle', 'AVAILABLE', 'North Fire Station', 2);

INSERT INTO responders
    (responder_id, first_name, middle_name, last_name, phone, email,
     responder_type, availability, organization_id, unit_id)
VALUES
    (1, 'Aarav', NULL, 'Sharma', '9876501001', 'aarav.sharma@example.com', 'Dispatcher', 'AVAILABLE', 1, NULL),
    (2, 'Diya', 'R', 'Nair', '9876501002', 'diya.nair@example.com', 'Police Officer', 'AVAILABLE', 1, 1),
    (3, 'Kabir', NULL, 'Rao', '9876501003', 'kabir.rao@example.com', 'Firefighter', 'ON_DUTY', 2, 2),
    (4, 'Ananya', 'S', 'Iyer', '9876501004', 'ananya.iyer@example.com', 'Paramedic', 'ON_DUTY', 3, 3),
    (5, 'Ishaan', NULL, 'Patel', '9876501005', 'ishaan.patel@example.com', 'Firefighter', 'AVAILABLE', 2, 4);

INSERT INTO incidents
    (incident_id, incident_type, severity, location, status, created_at, resolved_at)
VALUES
    (101, 'Building Fire', 'HIGH', '18 MG Road, Central District', 'IN_PROGRESS', '2026-10-12 07:45:00', NULL),
    (102, 'Road Accident', 'MEDIUM', 'Outer Ring Road, Junction 5', 'IN_PROGRESS', '2026-10-12 07:55:00', NULL),
    (103, 'Medical Emergency', 'HIGH', '42 Lake View Street, South District', 'RESOLVED', '2026-10-11 19:10:00', '2026-10-11 20:05:00');

INSERT INTO calls
    (call_id, received_by, status, transcript, received_at, caller_name, priority, caller_phone, location, incident_id)
VALUES
    (1001, 1, 'PROCESSED', 'Caller reports smoke coming from the second floor of a residential building.', '2026-10-12 07:45:00', 'Rohan Mehta', 'HIGH', '9876511001', '18 MG Road, Central District', 101),
    (1002, 1, 'PROCESSED', 'A second caller confirms visible flames and asks for immediate assistance.', '2026-10-12 07:47:00', 'Meera Das', 'HIGH', '9876511002', '18 MG Road, Central District', 101),
    (1003, 1, 'PROCESSED', 'Caller reports a collision involving two cars; one person may be injured.', '2026-10-12 07:55:00', 'Vikram Joshi', 'MEDIUM', '9876511003', 'Outer Ring Road, Junction 5', 102),
    (1004, 2, 'CLOSED', 'Caller reports a person experiencing breathing difficulty. Medical team attended.', '2026-10-11 19:10:00', 'Sara Khan', 'HIGH', '9876511004', '42 Lake View Street, South District', 103);

INSERT INTO dispatches
    (dispatch_id, incident_id, unit_id, dispatched_at, status)
VALUES
    (5001, 101, 2, '2026-10-12 07:49:00', 'EN_ROUTE'),
    (5002, 101, 3, '2026-10-12 07:51:00', 'EN_ROUTE'),
    (5003, 102, 1, '2026-10-12 07:58:00', 'ON_SCENE'),
    (5004, 103, 3, '2026-10-11 19:15:00', 'COMPLETED');

INSERT INTO resources
    (resource_id, resource_name, status, quantity_available, resource_type, quantity_total, location, organization_id)
VALUES
    (201, 'Oxygen Cylinder', 'AVAILABLE', 18, 'Medical Supply', 20, 'South Medical Base', 3),
    (202, 'First Aid Kit', 'AVAILABLE', 12, 'Medical Supply', 15, 'Central Store', 3),
    (203, 'Fire Extinguisher', 'AVAILABLE', 25, 'Firefighting Equipment', 30, 'North Fire Station', 2),
    (204, 'Portable Generator', 'AVAILABLE', 4, 'Power Equipment', 5, 'North Fire Station', 2);

INSERT INTO dispatch_resources
    (dispatch_resource_id, dispatch_id, resource_id, quantity_assigned, quantity_returned)
VALUES
    (1, 5001, 203, 2, 0),
    (2, 5001, 204, 1, 0),
    (3, 5002, 201, 2, 0),
    (4, 5002, 202, 1, 0),
    (5, 5004, 201, 1, 1);

INSERT INTO incident_patients
    (incident_id, patient_no, patient_name, age, gender, patient_condition, created_at)
VALUES
    (102, 1, 'Patient A', 34, 'Female', 'Minor injuries', '2026-10-12 08:00:00'),
    (102, 2, 'Patient B', 41, 'Male', 'Under assessment', '2026-10-12 08:01:00'),
    (103, 1, 'Patient C', 67, 'Female', 'Breathing difficulty; stabilized', '2026-10-11 19:20:00');

INSERT INTO activity_logs
    (log_id, incident_id, action, action_time)
VALUES
    (1, 101, 'Incident created after emergency call', '2026-10-12 07:45:00'),
    (2, 101, 'Fire engine dispatched', '2026-10-12 07:49:00'),
    (3, 101, 'Ambulance dispatched', '2026-10-12 07:51:00'),
    (4, 102, 'Police unit dispatched to road accident', '2026-10-12 07:58:00'),
    (5, 103, 'Incident resolved after medical assistance', '2026-10-11 20:05:00');

SELECT 'organizations' AS table_name, COUNT(*) AS row_count FROM organizations
UNION ALL SELECT 'responders', COUNT(*) FROM responders
UNION ALL SELECT 'units', COUNT(*) FROM units
UNION ALL SELECT 'incidents', COUNT(*) FROM incidents
UNION ALL SELECT 'calls', COUNT(*) FROM calls
UNION ALL SELECT 'dispatches', COUNT(*) FROM dispatches
UNION ALL SELECT 'resources', COUNT(*) FROM resources
UNION ALL SELECT 'dispatch_resources', COUNT(*) FROM dispatch_resources
UNION ALL SELECT 'incident_patients', COUNT(*) FROM incident_patients
UNION ALL SELECT 'activity_logs', COUNT(*) FROM activity_logs;
