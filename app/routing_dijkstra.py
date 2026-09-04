"""
Dijkstra's algorithm — single-source, multiple-destination routing.
Used for the "safe shelter finder" feature: instead of just checking
the nearest shelter as the crow flies, this computes the actual
risk-weighted road cost from the user to EVERY nearby shelter at once,
so we can recommend the best one (not just the nearest one).

Unlike A*, this has no single goal and no heuristic — it explores
outward from the start node until all reachable nodes have their
shortest cost known, which is exactly what "compare against several
shelters simultaneously" needs.
"""
import heapq


def dijkstra_multi_target(graph: dict, start_id: int, target_ids: list[int]) -> dict:
    """
    graph: {node_id: [(neighbor_id, distance_m, risk_weight), ...], ...}
    start_id: node to route FROM
    target_ids: list of node IDs we care about reaching (e.g. shelter locations)

    Returns: {target_id: {"path": [...], "total_cost": float}, ...}
             for every target that's reachable. Unreachable targets are omitted.
    """
    if start_id not in graph:
        return {}

    g_score = {start_id: 0.0}
    came_from = {}
    visited = set()

    open_set = [(0.0, start_id)]

    remaining_targets = set(target_ids)

    while open_set and remaining_targets:
        current_cost, current = heapq.heappop(open_set)

        if current in visited:
            continue
        visited.add(current)

        if current in remaining_targets:
            remaining_targets.discard(current)

        for neighbor_id, distance_m, risk_weight in graph.get(current, []):
            if neighbor_id in visited:
                continue

            edge_cost = distance_m * risk_weight
            tentative_g = g_score[current] + edge_cost

            if neighbor_id not in g_score or tentative_g < g_score[neighbor_id]:
                came_from[neighbor_id] = current
                g_score[neighbor_id] = tentative_g
                heapq.heappush(open_set, (tentative_g, neighbor_id))

    # Build result only for targets we actually reached
    results = {}
    for target_id in target_ids:
        if target_id in g_score:
            path = _reconstruct_path(came_from, target_id, start_id)
            results[target_id] = {
                "path": path,
                "total_cost": round(g_score[target_id], 2),
            }

    return results


def _reconstruct_path(came_from: dict, current: int, start_id: int) -> list:
    path = [current]
    while current != start_id and current in came_from:
        current = came_from[current]
        path.append(current)
    path.reverse()
    return path


def best_target(results: dict) -> tuple:
    """Given dijkstra_multi_target's output, returns (target_id, info) for the lowest-cost option."""
    if not results:
        return None, None
    best_id = min(results, key=lambda t: results[t]["total_cost"])
    return best_id, results[best_id]


if __name__ == "__main__":
    # Same diamond graph as the A* test, but now node 1 is the user,
    # and both node 2 AND node 3 are candidate shelters -> compare both
    graph = {
        1: [(2, 1000, 8.0), (4, 1000, 1.0)],   # 1->2 is risky
        2: [(1, 1000, 8.0), (3, 1000, 1.0)],
        3: [(2, 1000, 1.0), (4, 1000, 1.0)],
        4: [(1, 1000, 1.0), (3, 1000, 1.0)],
    }

    results = dijkstra_multi_target(graph, start_id=1, target_ids=[2, 3])
    print("Cost to reach each candidate shelter from node 1:")
    for target, info in results.items():
        print(f"  Shelter at node {target}: cost={info['total_cost']}, path={info['path']}")

    best_id, best_info = best_target(results)
    print(f"\nBest shelter choice: node {best_id} (cost {best_info['total_cost']})")
    print("Expected: node 3 wins, since reaching node 2 directly is expensive (risky edge)")