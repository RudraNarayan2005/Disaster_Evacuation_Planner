"""
Ties A*/Dijkstra to the real database: loads the road_nodes/road_edges
graph from PostgreSQL, applies live ML risk weights, and exposes the
functions app/main.py's route endpoints will call.

NOTE: road_nodes/road_edges are currently EMPTY in your database — the
schema has the tables, but no actual Odisha road network has been
loaded yet (that requires OSM road data, which is a separate data-
loading step). Until that's done, these functions will return "no
route found" against the real DB — that's expected, not a bug. The
graph-building and algorithm logic itself is already fully tested
against the hand-built graphs in the previous two files.
"""
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.routing_astar import astar_route
from app.routing_dijkstra import dijkstra_multi_target, best_target


def load_graph_from_db(db: Session) -> tuple[dict, dict]:
    """
    Builds the in-memory graph structure from road_nodes/road_edges.
    Returns (graph, node_coords) in the format routing_astar.py and
    routing_dijkstra.py expect.
    """
    nodes = db.execute(text("""
        SELECT id, ST_Y(location::geometry) AS lat, ST_X(location::geometry) AS lng
        FROM road_nodes
    """)).mappings().all()

    node_coords = {n["id"]: (n["lat"], n["lng"]) for n in nodes}

    edges = db.execute(text("""
        SELECT from_node, to_node, distance_m, risk_weight
        FROM road_edges
        WHERE is_closed = false
    """)).mappings().all()

    graph: dict = {node_id: [] for node_id in node_coords}
    for e in edges:
        # Treat roads as bidirectional (both directions traversable)
        graph.setdefault(e["from_node"], []).append((e["to_node"], e["distance_m"], e["risk_weight"]))
        graph.setdefault(e["to_node"], []).append((e["from_node"], e["distance_m"], e["risk_weight"]))

    return graph, node_coords


def find_nearest_road_node(db: Session, lat: float, lng: float) -> int | None:
    """Snaps a raw lat/lng (e.g. user's GPS location) to the nearest road_nodes entry."""
    result = db.execute(text("""
        SELECT id FROM road_nodes
        ORDER BY location <-> ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography
        LIMIT 1
    """), {"lat": lat, "lng": lng}).scalar()
    return result


def compute_safest_route(db: Session, user_lat: float, user_lng: float, shelter_lat: float, shelter_lng: float) -> dict:
    """
    The main entry point: given a user's location and a target shelter's
    location, snaps both to the road network and runs A* between them.
    """
    graph, node_coords = load_graph_from_db(db)

    if not graph:
        return {"error": "Road network is empty — road_nodes/road_edges need to be loaded first."}

    start_node = find_nearest_road_node(db, user_lat, user_lng)
    goal_node = find_nearest_road_node(db, shelter_lat, shelter_lng)

    if start_node is None or goal_node is None:
        return {"error": "Could not snap start or goal to the road network."}

    result = astar_route(graph, node_coords, start_node, goal_node)

    if result.get("path"):
        result["path_coords"] = [node_coords[n] for n in result["path"]]

    return result


def compute_best_shelter_route(db: Session, user_lat: float, user_lng: float, candidate_shelter_ids: dict) -> dict:
    """
    candidate_shelter_ids: {shelter_db_id: (lat, lng), ...} — a few nearby
    shelters (e.g. from find_nearest_shelters()) to compare via Dijkstra.

    Returns the best one by actual risk-weighted road cost, not just
    straight-line distance.
    """
    graph, node_coords = load_graph_from_db(db)

    if not graph:
        return {"error": "Road network is empty — road_nodes/road_edges need to be loaded first."}

    start_node = find_nearest_road_node(db, user_lat, user_lng)
    if start_node is None:
        return {"error": "Could not snap user location to the road network."}

    # Snap each candidate shelter to its nearest road node
    target_node_to_shelter = {}
    for shelter_id, (lat, lng) in candidate_shelter_ids.items():
        node_id = find_nearest_road_node(db, lat, lng)
        if node_id is not None:
            target_node_to_shelter[node_id] = shelter_id

    if not target_node_to_shelter:
        return {"error": "Could not snap any candidate shelters to the road network."}

    results = dijkstra_multi_target(graph, start_node, list(target_node_to_shelter.keys()))
    best_node, best_info = best_target(results)

    if best_node is None:
        return {"error": "No candidate shelter is reachable via the current road network."}

    return {
        "best_shelter_id": target_node_to_shelter[best_node],
        "route": best_info,
        "all_options": {
            target_node_to_shelter[node_id]: info
            for node_id, info in results.items()
        },
    }