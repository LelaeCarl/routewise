from __future__ import annotations

from dataclasses import dataclass


ALLOWED_NODE_TYPES = {"port", "airport", "icd", "rail_hub", "road_hub"}
ALLOWED_EDGE_MODES = {"sea", "air", "rail", "road"}


@dataclass(frozen=True)
class Node:
    id: str
    name: str
    country: str
    city: str
    type: str
    description: str


@dataclass(frozen=True)
class Edge:
    id: str
    from_node: str
    to_node: str
    mode: str
    base_cost: float
    cost_per_kg: float
    minimum_charge: float
    time: float
    description: str

