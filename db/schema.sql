-- =====================================================================
-- Disaster Evacuation Planner — Database Schema
-- PostgreSQL + PostGIS
-- =====================================================================
-- Run this once, right after creating the database:
--   psql -U postgres -d disaster_evac_planner -f schema.sql
-- =====================================================================

-- Enable the PostGIS extension (must be run as a superuser once per DB)
CREATE EXTENSION IF NOT EXISTS postgis;

-- ---------------------------------------------------------------------
-- SHELTERS
-- Seeded from the OSDMA / CMRF shelter dataset (158 real shelters,
-- 25 districts). location uses GEOGRAPHY so distance/nearest-neighbor
-- queries are accurate in real-world meters, not flat Cartesian units.
-- ---------------------------------------------------------------------
CREATE TABLE shelters (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    district        TEXT,
    block           TEXT,
    gp              TEXT,
    village         TEXT,
    location_desc   TEXT,                       -- human-readable location text from source PDF
    shelter_type    TEXT CHECK (shelter_type IN ('MCS', 'MFS')),  -- Cyclone vs Flood shelter
    capacity        INT,                         -- fill in if/when known; NULL is fine for MVP
    is_open         BOOLEAN DEFAULT true,
    location        GEOGRAPHY(POINT, 4326) NOT NULL,
    geocode_level   TEXT,                        -- 'Village Level' / 'Block Level' / 'District Level'
                                                   -- (honesty flag on coordinate precision — see report notes)
    wheelchair_accessible BOOLEAN DEFAULT false,
    medical_support BOOLEAN DEFAULT false,
    contact_number  TEXT,
    created_at      TIMESTAMP DEFAULT now()
);

CREATE INDEX idx_shelters_location ON shelters USING GIST (location);
CREATE INDEX idx_shelters_district ON shelters (district);

-- ---------------------------------------------------------------------
-- RISK ZONES
-- Flood / cyclone / landslide danger polygons. risk_level is updated
-- live by the ML pipeline (flood_risk_model / cyclone_risk_model).
-- ---------------------------------------------------------------------
CREATE TABLE risk_zones (
    id              SERIAL PRIMARY KEY,
    zone_type       TEXT CHECK (zone_type IN ('flood', 'cyclone', 'landslide')),
    risk_level      INT CHECK (risk_level BETWEEN 1 AND 5),
    risk_probability FLOAT CHECK (risk_probability BETWEEN 0 AND 1), -- raw ML model output
    district        TEXT,
    geom            GEOGRAPHY(POLYGON, 4326) NOT NULL,
    last_updated    TIMESTAMP DEFAULT now()
);

CREATE INDEX idx_risk_zones_geom ON risk_zones USING GIST (geom);
CREATE INDEX idx_risk_zones_type ON risk_zones (zone_type);

-- ---------------------------------------------------------------------
-- ROAD NETWORK (for A* / Dijkstra)
-- Kept deliberately simple: nodes = intersections/points, edges = road
-- segments. risk_weight is recalculated whenever risk_zones update.
-- ---------------------------------------------------------------------
CREATE TABLE road_nodes (
    id              SERIAL PRIMARY KEY,
    osm_id          BIGINT UNIQUE,                -- OpenStreetMap node id; NULL for hand-built/demo nodes
    location        GEOGRAPHY(POINT, 4326) NOT NULL,
    label           TEXT,                         -- optional, e.g. junction name
    district        TEXT                          -- district used by live risk-weight synchronization
);

CREATE INDEX idx_road_nodes_location ON road_nodes USING GIST (location);
CREATE INDEX idx_road_nodes_district ON road_nodes (district);

CREATE TABLE road_edges (
    id              SERIAL PRIMARY KEY,
    from_node       INT REFERENCES road_nodes(id) ON DELETE CASCADE,
    to_node         INT REFERENCES road_nodes(id) ON DELETE CASCADE,
    distance_m      FLOAT NOT NULL,               -- base cost: real-world distance
    risk_weight     FLOAT DEFAULT 1.0,             -- multiplier from ML risk output
    is_closed       BOOLEAN DEFAULT false,         -- manual/admin road closure override
    last_updated    TIMESTAMP DEFAULT now()
);

CREATE INDEX idx_road_edges_from ON road_edges (from_node);
CREATE INDEX idx_road_edges_to ON road_edges (to_node);

-- ---------------------------------------------------------------------
-- INCIDENT REPORTS (user-submitted: blocked road, flooding, SOS)
-- ---------------------------------------------------------------------
CREATE TABLE incident_reports (
    id              SERIAL PRIMARY KEY,
    report_type     TEXT CHECK (report_type IN ('road_blocked', 'flooding', 'fallen_tree', 'sos', 'other')),
    reporter_location GEOGRAPHY(POINT, 4326),
    description     TEXT,
    status          TEXT DEFAULT 'open' CHECK (status IN ('open', 'verified', 'resolved')),
    created_at      TIMESTAMP DEFAULT now()
);

CREATE INDEX idx_incidents_location ON incident_reports USING GIST (reporter_location);
CREATE INDEX idx_incidents_status ON incident_reports (status);

-- ---------------------------------------------------------------------
-- WEATHER SNAPSHOTS (cache of live weather API pulls, used to retrain
-- risk scores on the polling cycle without hammering the external API)
-- ---------------------------------------------------------------------
CREATE TABLE weather_snapshots (
    id              SERIAL PRIMARY KEY,
    district        TEXT NOT NULL,
    rainfall_mm     FLOAT,
    wind_speed_kmph FLOAT,
    forecast_summary TEXT,
    recorded_at     TIMESTAMP DEFAULT now()
);

CREATE INDEX idx_weather_district_time ON weather_snapshots (district, recorded_at DESC);

-- ---------------------------------------------------------------------
-- ADMIN USERS (lightweight auth for the admin dashboard)
-- ---------------------------------------------------------------------
CREATE TABLE admin_users (
    id              SERIAL PRIMARY KEY,
    username        TEXT UNIQUE NOT NULL,
    password_hash   TEXT NOT NULL,
    created_at      TIMESTAMP DEFAULT now()
);

-- =====================================================================
-- Useful reference queries (not executed — for your notes/report)
-- =====================================================================
-- Nearest 5 open shelters to a point:
--   SELECT name, location FROM shelters
--   WHERE is_open = true
--   ORDER BY location <-> ST_MakePoint(:lng, :lat)::geography
--   LIMIT 5;
--
-- Is a point inside any active risk zone?
--   SELECT * FROM risk_zones
--   WHERE ST_Intersects(geom, ST_MakePoint(:lng, :lat)::geography);
--
-- Road segments crossing a risk zone (for risk_weight updates):
--   SELECT re.id FROM road_edges re
--   JOIN road_nodes n1 ON re.from_node = n1.id
--   JOIN road_nodes n2 ON re.to_node = n2.id
--   JOIN risk_zones rz ON ST_Intersects(rz.geom, ST_MakeLine(n1.location::geometry, n2.location::geometry)::geography)
--   WHERE rz.risk_level >= 3;
-- =====================================================================
