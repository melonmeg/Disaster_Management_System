-- =====================================================================
-- 10_geocoding.sql   (one-time migration, additive only)
-- Coordinates for the free-text locations in incidents.location and
-- units.base_location. incidents/units are NOT altered: results live in a
-- cache keyed by the trimmed location text, and are exposed through views.
--
-- status: RESOLVED  = provider returned one usable match
--         AMBIGUOUS = provider returned several far-apart matches (no coordinates stored)
--         NOT_FOUND = provider returned nothing
--         MANUAL    = coordinates entered by a dispatcher/admin
-- Rows with ERROR are never stored, so a provider outage is retried later.
-- =====================================================================

CREATE TABLE geocode_cache (
    location_key  VARCHAR(255) NOT NULL PRIMARY KEY,   -- TRIM(location); collation makes it case-insensitive
    status        ENUM('RESOLVED', 'AMBIGUOUS', 'NOT_FOUND', 'MANUAL') NOT NULL,
    latitude      DECIMAL(9,6) NULL,
    longitude     DECIMAL(9,6) NULL,
    display_name  VARCHAR(500) NULL,
    provider      VARCHAR(50)  NULL,
    resolved_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    resolved_by   INT NULL,                             -- app_users.user_id for MANUAL entries

    CONSTRAINT chk_geocode_coords CHECK (
        (status IN ('RESOLVED', 'MANUAL') AND latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180)
        OR (status IN ('AMBIGUOUS', 'NOT_FOUND') AND latitude IS NULL AND longitude IS NULL))
);
