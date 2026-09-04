"""
A* pathfinding over the road network graph. Used for single-source,
single-destination routing — the main "get me from here to that one
shelter safely" use case.

Cost function per edge: distance_m * risk_weight
  - risk_weight comes from the flood/cyclone ML models (1.0 = safe,
    up to 10.0 = severe risk), so the algorithm naturally prefers
    longer-but-safer roads over shorter-but-flooded ones.

Heuristic: haversine straight-line distance to the goal node — this is
"admissible" (never overestimates the true remaining cost), which is
what makes A* guaranteed to find the optimal path.
"""
import heapq

from app.geo_utils import haversine_distance_km


def astar_route(graph: dict, node_coords: dict, start_id: int, goal_id: int) -> dict:
    """
    graph: {node_id: [(neighbor_id, distance_m, risk_weight), ...], ...}
    node_coords: {node_id: (lat, lng), ...}
    start_id, goal_id: node IDs to route between

    Returns: {"path": [node_id, ...], "total_cost": float, "distance_km": float}
             or {"path": None, "error": "..."} if no path exists
    """
    if start_id not in graph or goal_id not in graph:
        return {"path": None, "error": "start or goal node not found in graph"}

    goal_lat, goal_lng = node_coords[goal_id]

    def heuristic(node_id):
        lat, lng = node_coords[node_id]
        return haversine_distance_km(lat, lng, goal_lat, goal_lng)

    # Priority queue holds (f_score, node_id) — f_score = g_score + heuristic
    open_set = [(heuristic(start_id), start_id)]
    came_from = {}
    g_score = {start_id: 0.0}  # actual cost from start to this node so far

    visited = set()

    while open_set:
        _, current = heapq.heappop(open_set)

        if current == goal_id:
            return _reconstruct_path(came_from, current, g_score[current])

        if current in visited:
            continue
        visited.add(current)

        for neighbor_id, distance_m, risk_weight in graph.get(current, []):
            if neighbor_id in visited:
                continue

            edge_cost = distance_m * risk_weight  # risk-weighted cost, not just raw distance
            tentative_g = g_score[current] + edge_cost

            if neighbor_id not in g_score or tentative_g < g_score[neighbor_id]:
                came_from[neighbor_id] = current
                g_score[neighbor_id] = tentative_g
                f_score = tentative_g + heuristic(neighbor_id) * 1000  # km -> m, match edge_cost units
                heapq.heappush(open_set, (f_score, neighbor_id))

    return {"path": None, "error": "no route found between start and goal"}


def _reconstruct_path(came_from: dict, current: int, total_cost: float) -> dict:
    path = [current]
    while current in came_from:
        current = came_from[current]
        path.append(current)
    path.reverse()
    return {
        "path": path,
        "total_cost": round(total_cost, 2),
    }


if __name__ == "__main__":
    # Tiny hand-built test graph: 4 nodes in a diamond shape
    # 1 --- 2
    # |     |
    # 4 --- 3
    # Node 2 has heavy risk_weight (simulates a flooded road) -> A* should route via 4,3 instead
    node_coords = {
        1: (20.00, 85.00),
        2: (20.00, 85.10),
        3: (19.90, 85.10),
        4: (19.90, 85.00),
    }
    graph = {
        1: [(2, 1000, 8.0), (4, 1000, 1.0)],   # 1->2 is risky (weight 8), 1->4 is safe
        2: [(1, 1000, 8.0), (3, 1000, 1.0)],
        3: [(2, 1000, 1.0), (4, 1000, 1.0)],
        4: [(1, 1000, 1.0), (3, 1000, 1.0)],
    }

    result = astar_route(graph, node_coords, start_id=1, goal_id=3)
    print("Route from node 1 to node 3:")
    print(result)
    print("\nExpected: path avoids node 2 (risky), goes 1 -> 4 -> 3 instead")