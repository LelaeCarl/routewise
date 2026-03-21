from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

from backend.models import ALLOWED_EDGE_MODES, ALLOWED_NODE_TYPES, Edge, Node


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

        edges.append(
            Edge(
                id=str(item["id"]),
                from_node=str(item["from"]),
                to_node=str(item["to"]),
                mode=str(item["mode"]),
                base_cost=base_cost,
                cost_per_kg=cost_per_kg,
                minimum_charge=minimum_charge,
                time=float(item["time"]),
                description=str(item.get("description", "")),
            )
        )
    return edges


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

