from __future__ import annotations

import heapq
from dataclasses import asdict
from typing import Dict, List, Optional, Tuple

from backend.data_loader import load_network
from backend.models import Node


OBJECTIVE_LABELS = {
    "lowest_cost": "Lowest cost",
    "fastest_delivery": "Fastest delivery",
    "balanced_tradeoff": "Balanced trade-off",
}

MODE_LABELS = {
    "sea": "Sea",
    "air": "Air",
    "rail": "Rail",
    "road": "Road",
}


class RouteEngine:
    """
    Dijkstra-based routing over the seeded directed logistics network.

    Edge costs are computed dynamically from a weight-based pricing model:
        cost = max(base_cost + weight_kg * cost_per_kg, minimum_charge)

    This means routing decisions change with shipment weight — light shipments
    favour air (low base cost), heavy shipments favour sea (low per-kg rate).
    """

    DEFAULT_WEIGHT_KG = 500.0

    def __init__(self) -> None:
        nodes, edges = load_network()
        self._node_map: Dict[str, Node] = {n.id: n for n in nodes}
        self._edges = edges

        self._adj: Dict[str, List] = {}
        for e in edges:
            self._adj.setdefault(e.from_node, []).append(e)

        self._max_time = max((e.time for e in edges), default=0.0) or 1.0

    @staticmethod
    def compute_edge_cost(edge, weight_kg: float) -> float:
        """Compute the shipment cost for an edge at a given weight."""
        return max(edge.base_cost + weight_kg * edge.cost_per_kg, edge.minimum_charge)

    def _edge_weight(self, edge, objective_key: str, weight_kg: float, max_cost: float) -> float:
        if objective_key == "lowest_cost":
            return self.compute_edge_cost(edge, weight_kg)
        if objective_key == "fastest_delivery":
            return edge.time
        if objective_key == "balanced_tradeoff":
            normalized_cost = self.compute_edge_cost(edge, weight_kg) / max_cost
            normalized_time = edge.time / self._max_time
            return 0.5 * normalized_cost + 0.5 * normalized_time
        raise ValueError(f"Unknown objective key: {objective_key}")

    def compute_route(
        self,
        origin_id: str,
        destination_id: str,
        objective_key: str,
        weight_kg: float | None = None,
    ) -> dict:
        wkg = weight_kg if weight_kg is not None else self.DEFAULT_WEIGHT_KG

        if origin_id not in self._node_map or destination_id not in self._node_map:
            return {
                "success": False,
                "error": "Invalid origin or destination selection.",
            }

        origin = self._node_map[origin_id]
        destination = self._node_map[destination_id]

        if origin_id == destination_id:
            return {
                "success": True,
                "objective_key": objective_key,
                "origin": asdict(origin),
                "destination": asdict(destination),
                "path_node_ids": [origin_id],
                "path_nodes": [asdict(origin)],
                "legs": [],
                "total_cost": 0.0,
                "total_time": 0.0,
                "modes_used": [],
                "route_label": f"{OBJECTIVE_LABELS.get(objective_key, objective_key)} route",
                "route_rationale": "Origin and destination are the same node.",
            }

        max_cost = max(
            (self.compute_edge_cost(e, wkg) for e in self._edges), default=1.0
        ) or 1.0

        dist: Dict[str, float] = {origin_id: 0.0}
        prev_node: Dict[str, Optional[str]] = {origin_id: None}
        prev_edge = {}

        heap: List[Tuple[float, str]] = [(0.0, origin_id)]

        while heap:
            current_weight, u = heapq.heappop(heap)
            if current_weight != dist.get(u, float("inf")):
                continue

            if u == destination_id:
                break

            for edge in self._adj.get(u, []):
                v = edge.to_node
                w = self._edge_weight(edge, objective_key, wkg, max_cost)
                new_w = current_weight + w
                if new_w < dist.get(v, float("inf")):
                    dist[v] = new_w
                    prev_node[v] = u
                    prev_edge[v] = edge
                    heapq.heappush(heap, (new_w, v))

        if destination_id not in prev_node:
            return {
                "success": False,
                "error": "No route exists between the selected endpoints in the available network.",
            }

        node_ids_rev: List[str] = []
        legs_rev: List = []

        cursor = destination_id
        node_ids_rev.append(cursor)
        while cursor != origin_id:
            edge = prev_edge.get(cursor)
            if edge is None:
                return {
                    "success": False,
                    "error": "Route reconstruction failed due to missing edge data.",
                }
            legs_rev.append(edge)
            cursor = prev_node[cursor]  # type: ignore[assignment]
            node_ids_rev.append(cursor)

        node_ids = list(reversed(node_ids_rev))
        legs = list(reversed(legs_rev))

        total_cost = sum(self.compute_edge_cost(e, wkg) for e in legs)
        total_time = sum(e.time for e in legs)

        modes_used: List[str] = []
        seen_modes = set()
        for e in legs:
            label = MODE_LABELS.get(e.mode, e.mode)
            if label not in seen_modes:
                seen_modes.add(label)
                modes_used.append(label)

        path_nodes = [asdict(self._node_map[nid]) for nid in node_ids]
        leg_dicts = [
            {
                "from": asdict(self._node_map[l.from_node]),
                "to": asdict(self._node_map[l.to_node]),
                "from_id": l.from_node,
                "to_id": l.to_node,
                "mode": MODE_LABELS.get(l.mode, l.mode),
                "mode_key": l.mode,
                "cost": self.compute_edge_cost(l, wkg),
                "time": l.time,
                "description": getattr(l, "description", "") or "",
            }
            for l in legs
        ]

        obj_label = OBJECTIVE_LABELS.get(objective_key, objective_key)
        mode_summary = ", ".join(modes_used) if modes_used else "\u2014"

        if objective_key == "lowest_cost":
            rationale = "This route is selected to minimize total estimated cost across the available network."
        elif objective_key == "fastest_delivery":
            rationale = "This route is selected to minimize total estimated transit time across the available network."
        else:
            rationale = (
                "This route is selected using a balanced cost/time trade-off. "
                "Each edge is scored with normalized cost and time, then summed."
            )

        return {
            "success": True,
            "objective_key": objective_key,
            "origin": asdict(origin),
            "destination": asdict(destination),
            "path_node_ids": node_ids,
            "path_nodes": path_nodes,
            "legs": leg_dicts,
            "total_cost": total_cost,
            "total_time": total_time,
            "modes_used": modes_used,
            "route_label": f"{obj_label} route via {mode_summary}",
            "route_rationale": rationale,
        }


def route_engine_quick_checks(weight_kg: float = 500.0) -> dict:
    """Lightweight manual checks for development."""

    engine = RouteEngine()

    scenarios = [
        ("shanghai_port", "nairobi_icd", "lowest_cost"),
        ("guangzhou_airport", "nairobi_airport", "fastest_delivery"),
        ("shenzhen_port", "kisumu_hub", "balanced_tradeoff"),
        ("shanghai_port", "mombasa_port", "lowest_cost"),
    ]

    out = {"engine": "dijkstra", "weight_kg": weight_kg, "scenarios": []}
    for origin, destination, obj in scenarios:
        r = engine.compute_route(origin, destination, obj, weight_kg)
        if r.get("success"):
            out["scenarios"].append(
                {
                    "origin": origin,
                    "destination": destination,
                    "objective": obj,
                    "total_cost": r["total_cost"],
                    "total_time": r["total_time"],
                    "modes_used": r["modes_used"],
                    "legs": len(r["legs"]),
                }
            )
        else:
            out["scenarios"].append(
                {"origin": origin, "destination": destination, "objective": obj, "error": r.get("error")}
            )
    return out

