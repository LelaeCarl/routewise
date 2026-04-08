from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

from backend.models import ALLOWED_EDGE_MODES, ALLOWED_NODE_TYPES, Edge, Node


def _minmax_scale(value: float, in_min: float, in_max: float, out_min: float, out_max: float) -> float:
    if in_max <= in_min:
        return (out_min + out_max) / 2.0
    t = (value - in_min) / (in_max - in_min)
    return out_min + t * (out_max - out_min)


def _project_root() -> Path:
    # backend/ -> project root
    return Path(__file__).resolve().parent.parent


def _data_path(filename: str) -> Path:
    return _project_root() / "data" / filename


def load_nodes(path: str | None = None) -> List[Node]:
    nodes_path = Path(path) if path else _data_path("nodes.json")
    raw = json.loads(nodes_path.read_text(encoding="utf-8"))

    nodes: List[Node] = []
    for item in raw:
        nodes.append(
            Node(
                id=str(item["id"]),
                name=str(item["name"]),
                country=str(item["country"]),
                city=str(item["city"]),
                type=str(item["type"]),
                description=str(item.get("description", "")),
            )
        )
    return nodes


def load_edges(path: str | None = None) -> List[Edge]:
    edges_path = Path(path) if path else _data_path("edges.json")
    raw = json.loads(edges_path.read_text(encoding="utf-8"))

    # Rescale existing dataset attributes into realistic ranges per mode.
    # This preserves the seeded network structure while enforcing consistent units.
    target = {
        "sea": {"base_cost": (4000.0, 8000.0), "cost_per_kg": (0.6, 1.2), "time": (25.0, 40.0)},
        # Air base_cost kept low so light shipments don't explode in price.
        "air": {"base_cost": (50.0, 250.0), "cost_per_kg": (30.0, 50.0), "time": (3.0, 10.0)},
        "road": {"base_cost": (500.0, 1500.0), "cost_per_kg": (2.0, 4.0), "time": (1.0, 5.0)},
        "rail": {"base_cost": (1000.0, 2000.0), "cost_per_kg": (3.0, 5.0), "time": (3.0, 8.0)},
    }

    # Collect current mins/maxes per mode for proportional mapping (no arbitrary guessing).
    mins: Dict[str, Dict[str, float]] = {}
    maxs: Dict[str, Dict[str, float]] = {}
    for item in raw:
        mode = str(item.get("mode") or "")
        if mode not in target:
            continue
        if "base_cost" in item:
            base_cost = float(item["base_cost"])
            cost_per_kg = float(item["cost_per_kg"])
            minimum_charge = float(item["minimum_charge"])
        else:
            legacy_cost = float(item["cost"])
            base_cost = legacy_cost
            cost_per_kg = 0.0
            minimum_charge = legacy_cost
        time = float(item["time"])

        cur_min = mins.setdefault(
            mode,
            {"base_cost": base_cost, "cost_per_kg": cost_per_kg, "minimum_charge": minimum_charge, "time": time},
        )
        cur_max = maxs.setdefault(
            mode,
            {"base_cost": base_cost, "cost_per_kg": cost_per_kg, "minimum_charge": minimum_charge, "time": time},
        )
        cur_min["base_cost"] = min(cur_min["base_cost"], base_cost)
        cur_min["cost_per_kg"] = min(cur_min["cost_per_kg"], cost_per_kg)
        cur_min["minimum_charge"] = min(cur_min["minimum_charge"], minimum_charge)
        cur_min["time"] = min(cur_min["time"], time)
        cur_max["base_cost"] = max(cur_max["base_cost"], base_cost)
        cur_max["cost_per_kg"] = max(cur_max["cost_per_kg"], cost_per_kg)
        cur_max["minimum_charge"] = max(cur_max["minimum_charge"], minimum_charge)
        cur_max["time"] = max(cur_max["time"], time)

    edges: List[Edge] = []
    for item in raw:
        if "base_cost" in item:
            base_cost = float(item["base_cost"])
            cost_per_kg = float(item["cost_per_kg"])
            minimum_charge = float(item["minimum_charge"])
        else:
            legacy_cost = float(item["cost"])
            base_cost = legacy_cost
            cost_per_kg = 0.0
            minimum_charge = legacy_cost

        mode = str(item["mode"])
        time_val = float(item["time"])

        if mode in target and mode in mins and mode in maxs:
            bmin, bmax = target[mode]["base_cost"]
            rmin, rmax = target[mode]["cost_per_kg"]
            tmin, tmax = target[mode]["time"]

            base_cost = _minmax_scale(base_cost, mins[mode]["base_cost"], maxs[mode]["base_cost"], bmin, bmax)
            cost_per_kg = _minmax_scale(cost_per_kg, mins[mode]["cost_per_kg"], maxs[mode]["cost_per_kg"], rmin, rmax)
            time_val = _minmax_scale(time_val, mins[mode]["time"], maxs[mode]["time"], tmin, tmax)

            # Minimum charge (air only): use realistic small-shipment floors.
            if mode == "air":
                minimum_charge = _minmax_scale(
                    minimum_charge,
                    mins[mode]["minimum_charge"],
                    maxs[mode]["minimum_charge"],
                    300.0,
                    800.0,
                )
                minimum_charge = round(minimum_charge, 0)

                # Direct air routes should not be slower than multi-leg hub routings.
                # Keep within the required 3–10 day range.
                desc = str(item.get("description", "") or "").lower()
                if "direct air route" in desc:
                    time_val = min(time_val, 6.5)

            # Keep reasonable numeric shape.
            base_cost = round(base_cost, 0)
            cost_per_kg = round(cost_per_kg, 2)
            time_val = round(time_val, 1)

        edges.append(
            Edge(
                id=str(item["id"]),
                from_node=str(item["from"]),
                to_node=str(item["to"]),
                mode=mode,
                base_cost=base_cost,
                cost_per_kg=cost_per_kg,
                minimum_charge=minimum_charge,
                time=time_val,
                description=str(item.get("description", "")),
            )
        )

    # Practical realism: where both rail and road exist between the same endpoints,
    # rail should typically be faster than road on that corridor.
    by_pair: Dict[tuple[str, str], Dict[str, List[int]]] = {}
    for idx, e in enumerate(edges):
        by_pair.setdefault((e.from_node, e.to_node), {}).setdefault(e.mode, []).append(idx)

    adjusted = list(edges)
    for (frm, to), modes in by_pair.items():
        if "road" not in modes or "rail" not in modes:
            continue
        # Use the first edge for each mode (dataset uses at most one per direction today).
        road = edges[modes["road"][0]]
        rail_idx = modes["rail"][0]
        rail = edges[rail_idx]
        desired_rail_time = max(3.0, min(8.0, road.time - 1.5))
        desired_rail_rate = max(3.0, min(5.0, road.cost_per_kg + 0.30))
        desired_rail_base = max(1000.0, min(2000.0, road.base_cost + 300.0))

        new_time = round(min(rail.time, desired_rail_time), 1)
        new_rate = round(min(rail.cost_per_kg, desired_rail_rate), 2)
        new_base = round(min(rail.base_cost, desired_rail_base), 0)

        if new_time != rail.time or new_rate != rail.cost_per_kg or new_base != rail.base_cost:
            adjusted[rail_idx] = Edge(
                id=rail.id,
                from_node=rail.from_node,
                to_node=rail.to_node,
                mode=rail.mode,
                base_cost=new_base,
                cost_per_kg=new_rate,
                minimum_charge=rail.minimum_charge,
                time=new_time,
                description=rail.description,
            )

    return adjusted


def get_node_map(nodes: List[Node]) -> Dict[str, Node]:
    node_map: Dict[str, Node] = {}
    for node in nodes:
        if node.id in node_map:
            raise ValueError(f"Duplicate node id: {node.id}")
        node_map[node.id] = node
    return node_map


def validate_network(nodes: List[Node], edges: List[Edge]) -> None:
    node_map = get_node_map(nodes)

    for node in nodes:
        if node.type not in ALLOWED_NODE_TYPES:
            raise ValueError(f"Invalid node type '{node.type}' for node '{node.id}'")

        if not node.name.strip():
            raise ValueError(f"Node '{node.id}' has an empty name")

    for edge in edges:
        if edge.mode not in ALLOWED_EDGE_MODES:
            raise ValueError(f"Invalid edge mode '{edge.mode}' for edge '{edge.id}'")

        if edge.base_cost < 0:
            raise ValueError(f"Edge '{edge.id}' must have non-negative base_cost")
        if edge.cost_per_kg < 0:
            raise ValueError(f"Edge '{edge.id}' must have non-negative cost_per_kg")
        if edge.minimum_charge <= 0:
            raise ValueError(f"Edge '{edge.id}' must have positive minimum_charge")
        if edge.time <= 0:
            raise ValueError(f"Edge '{edge.id}' must have positive time")

        if edge.from_node not in node_map:
            raise ValueError(f"Edge '{edge.id}' references missing from node: {edge.from_node}")
        if edge.to_node not in node_map:
            raise ValueError(f"Edge '{edge.id}' references missing to node: {edge.to_node}")


def load_network() -> Tuple[List[Node], List[Edge]]:
    nodes = load_nodes()
    edges = load_edges()
    validate_network(nodes, edges)
    return nodes, edges

