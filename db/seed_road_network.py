"""
Seeds a REAL road network for the 9 tracked districts (Puri, Kendrapara,
Ganjam, Jagatsinghpur, Bhadrak, Balasore, Cuttack, Khordha, Gajapati —
see app/weather_service.py DISTRICT_PROFILES) using live OpenStreetMap
data pulled from the Overpass API.

This replaces the old 5-node Puri-only demo network (kept for reference
at db/seed_road_network_puri_demo.py).

For each district:
  1. Build a bounding box covering the district centroid + every real
     shelter seeded for that district (with padding), so routes to
     actual shelters have road coverage, not just the district center.
  2. Query Overpass for drivable highway ways inside that bbox.
  3. Insert each way's nodes into road_nodes (deduped across districts
     by OSM node id, via the osm_id column — see db/schema.sql /
     db/migrate_add_osm_id.sql) and each consecutive node pair into
     road_edges (distance computed with haversine).

REQUIRES REAL INTERNET ACCESS to overpass-api.de. Run this from your
own machine (not a sandboxed/offline environment):

    python -m db.seed_road_network

Overpass is a shared free public service — this script deliberately
pauses briefly between districts to avoid hammering it. A full run for
9 districts typically takes a few minutes.
"""
import csv
import os
import sys
import time

import httpx

# allow running this as a script from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from app.database import engine
from app.geo_utils import haversine_distance_km
from app.weather_service import DISTRICT_PROFILES

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
SHELTERS_CSV = os.path.join(os.path.dirname(__file__), "..", "data", "odisha_shelters_geocoded.csv")

# "Drivable" road types — enough for evacuation routing without pulling in
# footpaths, cycleways, etc. that a car/rescue vehicle can't use.
HIGHWAY_TYPES = (
    "motorway|trunk|primary|secondary|tertiary|unclassified|residential|"
    "motorway_link|trunk_link|primary_link|secondary_link|tertiary_link"
)

BBOX_PADDING_DEG = 0.05  # ~5km padding around the district centroid + its shelters
REQUEST_TIMEOUT_S = 120
PAUSE_BETWEEN_DISTRICTS_S = 2  # be polite to the free Overpass endpoint


def load_shelter_rows() -> list[dict]:
    with open(SHELTERS_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def get_district_bbox(district: str, shelter_rows: list[dict]) -> tuple[float, float, float, float]:
    """
    Returns (south, west, north, east) covering the district centroid
    (from DISTRICT_PROFILES) and every shelter row belonging to that
    district in the CSV, plus padding.
    """
    profile = DISTRICT_PROFILES[district]
    lats = [profile["lat"]]
    lngs = [profile["lng"]]

    for row in shelter_rows:
        if row["District"].strip() == district:
            try:
                lats.append(float(row["Latitude"]))
                lngs.append(float(row["Longitude"]))
            except (ValueError, KeyError):
                continue

    south = min(lats) - BBOX_PADDING_DEG
    north = max(lats) + BBOX_PADDING_DEG
    west = min(lngs) - BBOX_PADDING_DEG
    east = max(lngs) + BBOX_PADDING_DEG
    return south, west, north, east


def fetch_osm_roads(bbox: tuple[float, float, float, float]) -> dict:
    """Queries Overpass for drivable roads inside bbox = (south, west, north, east)."""
    south, west, north, east = bbox
    query = f"""
    [out:json][timeout:90];
    (
      way["highway"~"^({HIGHWAY_TYPES})$"]({south},{west},{north},{east});
    );
    out body;
    >;
    out skel qt;
    """
    response = httpx.post(OVERPASS_URL, data={"data": query}, timeout=REQUEST_TIMEOUT_S)
    response.raise_for_status()
    return response.json()


def parse_osm_response(osm_data: dict) -> tuple[dict, list]:
    """
    osm_data: raw Overpass JSON (elements = mix of 'node' and 'way' objects)

    Returns:
      node_coords: {osm_node_id: (lat, lng), ...} for every node referenced by a road way
      edges: [(osm_from_id, osm_to_id, distance_m), ...] for every consecutive
             pair of nodes within every way (i.e. each road segment)
    """
    node_coords: dict = {}
    way_node_lists: list = []

    for el in osm_data.get("elements", []):
        if el["type"] == "node":
            node_coords[el["id"]] = (el["lat"], el["lon"])
        elif el["type"] == "way":
            way_node_lists.append(el.get("nodes", []))

    edges = []
    for node_ids in way_node_lists:
        for a, b in zip(node_ids, node_ids[1:]):
            if a in node_coords and b in node_coords and a != b:
                lat1, lng1 = node_coords[a]
                lat2, lng2 = node_coords[b]
                distance_m = haversine_distance_km(lat1, lng1, lat2, lng2) * 1000
                edges.append((a, b, distance_m))

    return node_coords, edges


def upsert_nodes(conn, node_coords: dict, district: str) -> dict:
    """
    Inserts nodes, deduped by osm_id (a node shared by two overlapping
    district bboxes is only stored once). Returns
    {osm_id: internal_road_nodes_id, ...} for edge-building.
    """
    osm_to_internal = {}
    for osm_id, (lat, lng) in node_coords.items():
        internal_id = conn.execute(text("""
            INSERT INTO road_nodes (osm_id, location, label, district)
            VALUES (:osm_id, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography, NULL, :district)
            ON CONFLICT (osm_id) DO UPDATE SET
                district = COALESCE(road_nodes.district, EXCLUDED.district)
            RETURNING id
        """), {"osm_id": osm_id, "lat": lat, "lng": lng}).scalar()
        osm_to_internal[osm_id] = internal_id
    return osm_to_internal


def insert_edges(conn, osm_to_internal: dict, edges: list) -> int:
    inserted = 0
    for osm_from, osm_to, distance_m in edges:
        from_id = osm_to_internal.get(osm_from)
        to_id = osm_to_internal.get(osm_to)
        if from_id is None or to_id is None or from_id == to_id:
            continue
        conn.execute(text("""
            INSERT INTO road_edges (from_node, to_node, distance_m, risk_weight)
            VALUES (:from_id, :to_id, :distance_m, 1.0)
        """), {"from_id": from_id, "to_id": to_id, "distance_m": distance_m})
        inserted += 1
    return inserted


def seed():
    shelter_rows = load_shelter_rows()

    total_nodes = 0
    total_edges = 0

    with engine.begin() as conn:
        # Wipe any previous network (safe to re-run; road_edges cascades
        # via road_nodes FK anyway, but be explicit)
        conn.execute(text("DELETE FROM road_edges"))
        conn.execute(text("DELETE FROM road_nodes"))

    for district in DISTRICT_PROFILES:
        print(f"\n--- {district} ---")
        bbox = get_district_bbox(district, shelter_rows)
        print(f"  Bounding box (S,W,N,E): {bbox}")

        try:
            osm_data = fetch_osm_roads(bbox)
        except httpx.HTTPError as e:
            print(f"  Overpass query failed for {district}: {e}")
            print("  Skipping this district — you can re-run the whole script "
                  "later once the endpoint is reachable again.")
            continue

        node_coords, edges = parse_osm_response(osm_data)
        print(f"  Fetched {len(node_coords)} nodes, {len(edges)} road segments from OSM")

        if not node_coords:
            print(f"  WARNING: no roads found for {district} — bbox may be too small "
                  f"or Overpass returned nothing. Check the bbox manually on "
                  f"https://overpass-turbo.eu if this looks wrong.")
            continue

        with engine.begin() as conn:
            osm_to_internal = upsert_nodes(conn, node_coords, district)
            edge_count = insert_edges(conn, osm_to_internal, edges)

        total_nodes += len(node_coords)
        total_edges += edge_count

        time.sleep(PAUSE_BETWEEN_DISTRICTS_S)

    print(f"\nDone. Seeded ~{total_nodes} road nodes and {total_edges} road edges "
          f"across {len(DISTRICT_PROFILES)} districts.")
    print("Sanity check once this finishes:")
    print("  SELECT COUNT(*) FROM road_nodes;")
    print("  SELECT COUNT(*) FROM road_edges;")
    print("Then hit /api/route with a real user lat/lng and a real shelter "
          "lat/lng inside one of the 9 districts.")


if __name__ == "__main__":
    seed()
