-- =====================================================================
-- 00_base_tables.sql
-- Creates the database and the two parent tables that
-- emergency_response.sql references but does not create
-- (organizations, responders). Column names/types are taken from
-- emergency_response_demo_data.sql.
--
-- Run order (fresh install):
--   1. sql/00_base_tables.sql
--   2. emergency_response.sql          (existing schema, unchanged)
--   3. emergency_response_demo_data.sql (existing sample data, unchanged)
--   4. sql/01_* ... sql/05_*            (or simply: python scripts/setup_db.py --bootstrap)
-- =====================================================================

CREATE DATABASE IF NOT EXISTS emergency_response_management
    CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

USE emergency_response_management;

CREATE TABLE IF NOT EXISTS organizations (
    organization_id INT AUTO_INCREMENT PRIMARY KEY,
    organization_name VARCHAR(100) NOT NULL,
    location VARCHAR(255),
    status VARCHAR(30) DEFAULT 'ACTIVE',

    CONSTRAINT uq_organizations_name UNIQUE (organization_name)
);

-- unit_id is added later by emergency_response.sql (ALTER TABLE responders ADD COLUMN unit_id)
CREATE TABLE IF NOT EXISTS responders (
    responder_id INT AUTO_INCREMENT PRIMARY KEY,
    first_name VARCHAR(50) NOT NULL,
    middle_name VARCHAR(50),
    last_name VARCHAR(50) NOT NULL,
    phone VARCHAR(20),
    email VARCHAR(100),
    responder_type VARCHAR(50),
    availability VARCHAR(30) DEFAULT 'AVAILABLE',
    organization_id INT NOT NULL,

    CONSTRAINT uq_responders_email UNIQUE (email),

    FOREIGN KEY (organization_id)
        REFERENCES organizations(organization_id)
);
