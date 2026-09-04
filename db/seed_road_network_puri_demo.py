"""
Seeds a basic road network for Puri district — real junction points
connected as a simple graph, enough to test A*/Dijkstra end to end.

This is intentionally small (not a full OSM import) so you have a
working, testable network right away. Scaling to more districts later
means either manually adding more nodes here, or writing an OSM
Overpass import script as a follow-up.

Run from the project root:
    python -m db.seed_road_network
"""
from sqlalchemy import text
from app.database import engine

# Real coordinates for major points in/around Puri town + route toward
# a couple of the shelters already in your database
ROAD_NODES = [
    {"id": 1, "lat": 19.8135, "lng": 85.8312, "label": "Puri Town Center"},
    {"id": 2, "lat": 19.8076, "lng": 85.8253, "label": "Puri-Krushnaprasad Rd Junction"},
    {"id": 3, "lat": 19.7883, "lng": 85.8014, "label": "Puri Sadar Rd"},
    {"id": 4, "lat": 19.7879, "lng": 85.6405, "label": "Brahmagiri Junction"},
    {"id": 5, "lat": 20.0623, "lng": 85.7433, "label": "Kanas Rd Junction"},
]

# Edges: (from_id, to_id, distance_m, risk_weight)
# distance_m is a reasonable real-world road-distance estimate (not
# straight-line) between these points
ROAD_EDGES = [
    (1, 2, 4500, 1.0),
    (2, 3, 6000, 1.0),
    (3, 4, 18000, 1.0),
    (2, 5, 32000, 1.0),
    (1, 5, 35000, 1.0),
]


def seed():
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM road_edges"))
        conn.execute(text("DELETE FROM road_nodes"))

        for node in ROAD_NODES:
            conn.execute(text("""
                INSERT INTO road_nodes (id, location, label)
                VALUES (:id, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography, :label)
            """), node)

        # Reset the sequence so future inserts don't collide with our manual IDs
        conn.execute(text("SELECT setval('road_nodes_id_seq', (SELECT MAX(id) FROM road_nodes))"))

        for from_id, to_id, distance_m, risk_weight in ROAD_EDGES:
            conn.execute(text("""
                INSERT INTO road_edges (from_node, to_node, distance_m, risk_weight)
                VALUES (:from_id, :to_id, :distance_m, :risk_weight)
            """), {"from_id": from_id, "to_id": to_id, "distance_m": distance_m, "risk_weight": risk_weight})

    print(f"Seeded {len(ROAD_NODES)} road nodes and {len(ROAD_EDGES)} road edges.")


if __name__ == "__main__":
    seed()