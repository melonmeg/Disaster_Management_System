-- =====================================================================
-- 06_roles_privileges.sql   DATABASE-LEVEL ACCESS CONTROL (re-runnable, needs root/DBA)
--
-- One MySQL role per application role. The API connects with a different
-- least-privilege MySQL account depending on who is logged in, so even a
-- bug in the API cannot let a responder delete data: MySQL itself refuses.
--
--   erm_role_auth        login/refresh only: read/update app_users
--   erm_role_admin       full DML + EXECUTE, but no DDL and no GRANT
--   erm_role_dispatcher  manage incidents, calls, dispatches, patients; run allocation procedures;
--                        no DELETE anywhere, no changes to organizations/units master data
--   erm_role_responder   mostly read-only; may update own availability, dispatch status,
--                        patients, and record returned resources via sp_return_resource
--
-- Login accounts (erm_auth, erm_admin, erm_dispatcher, erm_responder) are created by
-- scripts/setup_db.py with passwords from backend/.env. Manual equivalent:
--   CREATE USER 'erm_responder'@'localhost' IDENTIFIED BY '<password>';
--   GRANT erm_role_responder TO 'erm_responder'@'localhost';
--   SET DEFAULT ROLE ALL TO 'erm_responder'@'localhost';
-- =====================================================================

CREATE ROLE IF NOT EXISTS erm_role_auth, erm_role_admin, erm_role_dispatcher, erm_role_responder;

-- ---------- auth (used only by /auth/login, /auth/refresh, /auth/me) ----------
GRANT SELECT, UPDATE ON emergency_response_management.app_users TO erm_role_auth;

-- ---------- admin ----------
GRANT SELECT, INSERT, UPDATE, DELETE, EXECUTE, SHOW VIEW
    ON emergency_response_management.* TO erm_role_admin;

-- ---------- dispatcher ----------
GRANT SELECT ON emergency_response_management.organizations      TO erm_role_dispatcher;
GRANT SELECT ON emergency_response_management.units              TO erm_role_dispatcher;
GRANT SELECT ON emergency_response_management.resources          TO erm_role_dispatcher;
GRANT SELECT ON emergency_response_management.dispatch_resources TO erm_role_dispatcher;
GRANT SELECT ON emergency_response_management.activity_logs      TO erm_role_dispatcher;
GRANT SELECT, UPDATE (availability, unit_id)
             ON emergency_response_management.responders         TO erm_role_dispatcher;
GRANT SELECT, INSERT, UPDATE ON emergency_response_management.incidents         TO erm_role_dispatcher;
GRANT SELECT, INSERT, UPDATE ON emergency_response_management.calls             TO erm_role_dispatcher;
GRANT SELECT, INSERT, UPDATE ON emergency_response_management.dispatches        TO erm_role_dispatcher;
GRANT SELECT, INSERT, UPDATE ON emergency_response_management.incident_patients TO erm_role_dispatcher;
GRANT INSERT ON emergency_response_management.activity_logs TO erm_role_dispatcher;
GRANT SELECT ON emergency_response_management.v_incident_overview   TO erm_role_dispatcher;
GRANT SELECT ON emergency_response_management.v_unit_availability   TO erm_role_dispatcher;
GRANT SELECT ON emergency_response_management.v_resource_stock      TO erm_role_dispatcher;
GRANT SELECT ON emergency_response_management.v_active_dispatches   TO erm_role_dispatcher;
GRANT SELECT ON emergency_response_management.v_responder_directory TO erm_role_dispatcher;
GRANT EXECUTE ON PROCEDURE emergency_response_management.sp_create_dispatch   TO erm_role_dispatcher;
GRANT EXECUTE ON PROCEDURE emergency_response_management.sp_allocate_resource TO erm_role_dispatcher;
GRANT EXECUTE ON PROCEDURE emergency_response_management.sp_return_resource   TO erm_role_dispatcher;
GRANT EXECUTE ON PROCEDURE emergency_response_management.sp_resolve_incident  TO erm_role_dispatcher;
GRANT EXECUTE ON PROCEDURE emergency_response_management.sp_assign_responder  TO erm_role_dispatcher;
GRANT EXECUTE ON PROCEDURE emergency_response_management.sp_incident_report   TO erm_role_dispatcher;
GRANT EXECUTE ON FUNCTION emergency_response_management.fn_next_patient_no      TO erm_role_dispatcher;
GRANT EXECUTE ON FUNCTION emergency_response_management.fn_unit_is_free         TO erm_role_dispatcher;
GRANT EXECUTE ON FUNCTION emergency_response_management.fn_response_minutes     TO erm_role_dispatcher;
GRANT EXECUTE ON FUNCTION emergency_response_management.fn_outstanding_quantity TO erm_role_dispatcher;

-- ---------- responder ----------
-- No access to responders.email or app_users; read the directory view instead.
GRANT SELECT (responder_id, first_name, middle_name, last_name, responder_type,
              availability, organization_id, unit_id),
      UPDATE (availability)
    ON emergency_response_management.responders TO erm_role_responder;
GRANT SELECT ON emergency_response_management.organizations      TO erm_role_responder;
GRANT SELECT ON emergency_response_management.units              TO erm_role_responder;
GRANT SELECT ON emergency_response_management.incidents          TO erm_role_responder;
GRANT SELECT ON emergency_response_management.resources          TO erm_role_responder;
GRANT SELECT ON emergency_response_management.dispatch_resources TO erm_role_responder;
GRANT SELECT ON emergency_response_management.activity_logs      TO erm_role_responder;
GRANT SELECT, UPDATE (status) ON emergency_response_management.dispatches TO erm_role_responder;
GRANT SELECT, INSERT, UPDATE  ON emergency_response_management.incident_patients TO erm_role_responder;
GRANT INSERT ON emergency_response_management.activity_logs TO erm_role_responder;
GRANT SELECT ON emergency_response_management.v_incident_overview   TO erm_role_responder;
GRANT SELECT ON emergency_response_management.v_unit_availability   TO erm_role_responder;
GRANT SELECT ON emergency_response_management.v_resource_stock      TO erm_role_responder;
GRANT SELECT ON emergency_response_management.v_active_dispatches   TO erm_role_responder;
GRANT SELECT ON emergency_response_management.v_responder_directory TO erm_role_responder;
GRANT EXECUTE ON PROCEDURE emergency_response_management.sp_return_resource TO erm_role_responder;
GRANT EXECUTE ON PROCEDURE emergency_response_management.sp_incident_report TO erm_role_responder;
GRANT EXECUTE ON FUNCTION emergency_response_management.fn_next_patient_no      TO erm_role_responder;
GRANT EXECUTE ON FUNCTION emergency_response_management.fn_outstanding_quantity TO erm_role_responder;
