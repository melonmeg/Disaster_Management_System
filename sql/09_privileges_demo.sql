-- =====================================================================
-- 09_privileges_demo.sql   ROLE-BASED ACCESS CONTROL IN MYSQL (viva demo)
-- Part 1 runs as root. Part 2 is done by logging in as each account.
-- =====================================================================

-- ---------- Part 1: what each role may do ----------
SELECT FROM_USER AS role_name, TO_USER AS granted_to FROM mysql.role_edges
WHERE FROM_USER LIKE 'erm_role_%' ORDER BY FROM_USER;

SHOW GRANTS FOR erm_role_admin;
SHOW GRANTS FOR erm_role_dispatcher;
SHOW GRANTS FOR erm_role_responder;
SHOW GRANTS FOR erm_role_auth;

-- Column-level privileges (responder may only change availability / dispatch status)
SELECT GRANTEE, TABLE_NAME, COLUMN_NAME, PRIVILEGE_TYPE
FROM information_schema.COLUMN_PRIVILEGES
WHERE GRANTEE LIKE '%erm_role_%' ORDER BY GRANTEE, TABLE_NAME, COLUMN_NAME;

-- ---------- Part 2: try it (passwords are in backend/.env) ----------
-- mysql -u erm_responder -p emergency_response_management
--   SELECT incident_id, status FROM incidents;                     -- OK
--   SELECT responder_id, availability FROM responders;             -- OK (allowed columns)
--   SELECT email FROM responders;                                  -- ERROR 1143 column denied
--   SELECT * FROM calls;                                           -- ERROR 1142 table denied
--   UPDATE responders SET availability = 'ON_DUTY' WHERE responder_id = 2;   -- OK
--   UPDATE dispatches SET unit_id = 4 WHERE dispatch_id = 5003;    -- ERROR 1143 column denied
--   DELETE FROM incidents WHERE incident_id = 103;                 -- ERROR 1142
--   CALL sp_allocate_resource(5001, 202, 1);                       -- ERROR 1370 execute denied
--
-- mysql -u erm_dispatcher -p emergency_response_management
--   CALL sp_create_dispatch(102, 4, @id); SELECT @id;              -- OK (if unit 4 is free)
--   DELETE FROM calls WHERE call_id = 1001;                        -- ERROR 1142 (no DELETE)
--   SELECT * FROM app_users;                                       -- ERROR 1142 (password hashes hidden)
--   INSERT INTO organizations (organization_name) VALUES ('X');    -- ERROR 1142
--
-- mysql -u erm_admin -p emergency_response_management
--   DELETE FROM incident_patients WHERE incident_id = 0;           -- OK (DML allowed)
--   DROP TABLE calls;                                              -- ERROR 1142 (no DDL)
--   GRANT SELECT ON emergency_response_management.* TO erm_responder@localhost;  -- ERROR (no GRANT OPTION)
