-- =====================================================================
-- Migration: add osm_id to road_nodes
-- Only needed if you already ran schema.sql BEFORE this change.
-- If you're setting up the database fresh, skip this file — schema.sql
-- already includes osm_id.
--
-- Run with:
--   psql -U postgres -d disaster_evac_planner -f db/migrate_add_osm_id.sql
-- =====================================================================

ALTER TABLE road_nodes ADD COLUMN IF NOT EXISTS osm_id BIGINT UNIQUE;
