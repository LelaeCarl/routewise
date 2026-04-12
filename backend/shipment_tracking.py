"""Shipment tracking backend (Phase 1): persistence and helpers on top of route results.

Does not perform routing — consumes successful `RouteEngine.compute_route` output only.
"""

from __future__ import annotations

import json
import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from backend.db_models import Shipment
from backend.extensions import db
from backend.route_engine import OBJECTIVE_LABELS

# Ordered logistics statuses for timeline / progression (index = current_stage_index).
SHIPMENT_STATUSES: tuple[str, ...] = (
    "Shipment Created",
    "At Origin Hub",
    "In Transit",
    "At Transfer Hub",
    "Out for Delivery",
    "Delivered",
)

Phase = Literal["completed", "current", "upcoming"]


def normalize_tracking_number(value: str) -> str:
    return (value or "").strip().upper()


def generate_tracking_number() -> str:
    """Return a unique tracking id, e.g. RW-20260413-A7K2 (date + random suffix)."""
    d = datetime.now(timezone.utc).strftime("%Y%m%d")
    alphabet = string.ascii_uppercase + string.digits
    while True:
        suffix = "".join(secrets.choice(alphabet) for _ in range(4))
        candidate = f"RW-{d}-{suffix}"
        if Shipment.query.filter_by(tracking_number=candidate).first() is None:
            return candidate


def _json_safe(obj: Any) -> Any:
    """Best-effort JSON round-trip so only DB-storable structures are kept."""
    return json.loads(json.dumps(obj, default=str))


def build_path_summary(path_nodes: list[dict]) -> str:
    names = [str(n.get("name", "")).strip() for n in path_nodes if n]
    return " → ".join(names) if names else ""


def snapshot_route_data(route: dict) -> tuple[list, list, str]:
    """Extract legs, path nodes, and a short path summary from a successful route dict."""
    path_nodes = list(route.get("path_nodes") or [])
    legs = list(route.get("legs") or [])
    summary = build_path_summary(path_nodes)
    return _json_safe(legs), _json_safe(path_nodes), summary


def status_at_stage_index(index: int) -> str:
    if index < 0:
        index = 0
    if index >= len(SHIPMENT_STATUSES):
        index = len(SHIPMENT_STATUSES) - 1
    return SHIPMENT_STATUSES[index]


def format_status_display(status: str) -> str:
    """Normalize display string for a stored status."""
    return (status or "").strip() or SHIPMENT_STATUSES[0]


def milestone_timeline(
    shipment: Shipment,
) -> list[dict[str, Any]]:
    """Stages for a future tracking UI: completed / current / upcoming by stage index."""
    idx = int(shipment.current_stage_index or 0)
    out: list[dict[str, Any]] = []
    for i, label in enumerate(SHIPMENT_STATUSES):
        if i < idx:
            phase: Phase = "completed"
        elif i == idx:
            phase = "current"
        else:
            phase = "upcoming"
        out.append({"index": i, "status": label, "phase": phase})
    return out


def leg_milestones(shipment: Shipment) -> list[dict[str, Any]]:
    """Optional route-leg milestones (one row per leg) for timeline UIs."""
    legs = shipment.route_legs or []
    milestones: list[dict[str, Any]] = []
    for i, leg in enumerate(legs):
        frm = (leg.get("from") or {}).get("name", "")
        to = (leg.get("to") or {}).get("name", "")
        mode = leg.get("mode", "")
        milestones.append(
            {
                "leg_index": i,
                "from_name": frm,
                "to_name": to,
                "mode": mode,
                "summary": f"{frm} → {to} ({mode})" if frm or to else mode,
            }
        )
    return milestones


def _leg_display_row(leg: dict, leg_index: int) -> dict[str, Any]:
    frm = (leg.get("from") or {}).get("name", "")
    to = (leg.get("to") or {}).get("name", "")
    mode = leg.get("mode", "")
    mode_key = (leg.get("mode_key") or "").lower()
    return {
        "leg_index": leg_index,
        "from_name": frm,
        "to_name": to,
        "mode": mode,
        "mode_key": mode_key,
        "summary": f"{frm} → {to} ({mode})" if frm or to else mode,
        "time": leg.get("time"),
        "cost": leg.get("cost"),
    }


def route_leg_timeline(shipment: Shipment) -> list[dict[str, Any]]:
    """Per-leg rows with completed / current / upcoming for route path UI."""
    legs = shipment.route_legs or []
    if not legs:
        return []

    sci = int(shipment.current_stage_index or 0)
    last_stage = len(SHIPMENT_STATUSES) - 1
    if sci >= last_stage:
        return [{**_leg_display_row(leg, i), "phase": "completed"} for i, leg in enumerate(legs)]

    n = len(legs)
    p = sci / max(1, last_stage)
    out: list[dict[str, Any]] = []
    for i, leg in enumerate(legs):
        leg_start = i / n
        leg_end = (i + 1) / n
        if p + 1e-9 >= leg_end:
            phase: Phase = "completed"
        elif p >= leg_start:
            phase = "current"
        else:
            phase = "upcoming"
        out.append({**_leg_display_row(leg, i), "phase": phase})
    return out


def modes_used_summary(shipment: Shipment) -> str:
    """Comma-separated mode labels from legs (order preserved, unique)."""
    legs = shipment.route_legs or []
    seen: set[str] = set()
    parts: list[str] = []
    for leg in legs:
        m = str(leg.get("mode", "")).strip()
        if m and m not in seen:
            seen.add(m)
            parts.append(m)
    return ", ".join(parts) if parts else "—"


def create_shipment_from_route(
    *,
    route: dict,
    origin_id: str,
    destination_id: str,
    objective_key: str,
    weight_kg: float,
    user_id: int | None = None,
    direction_key: str | None = None,
    objective_label: str | None = None,
    initial_stage_index: int = 0,
) -> Shipment:
    """Persist a shipment from a successful planner route result.

    Raises ValueError if the route is not successful or missing required fields.
    """
    if not route.get("success"):
        raise ValueError("Cannot create a shipment from an unsuccessful route result.")

    legs, path_nodes, path_summary = snapshot_route_data(route)
    label = objective_label or OBJECTIVE_LABELS.get(objective_key, objective_key)

    origin = route.get("origin") or {}
    dest = route.get("destination") or {}
    origin_name = str(origin.get("name", origin_id))
    destination_name = str(dest.get("name", destination_id))

    total_cost = float(route.get("total_cost", 0.0))
    total_days = float(route.get("total_time", 0.0))

    stage_index = max(0, min(initial_stage_index, len(SHIPMENT_STATUSES) - 1))
    status = status_at_stage_index(stage_index)

    now = datetime.now(timezone.utc)
    estimated_arrival = now + timedelta(days=total_days) if total_days > 0 else None

    tracking_number = generate_tracking_number()

    shipment = Shipment(
        user_id=user_id,
        tracking_number=tracking_number,
        origin_id=origin_id,
        origin_name=origin_name,
        destination_id=destination_id,
        destination_name=destination_name,
        direction_key=direction_key,
        objective_key=objective_key,
        objective_label=label,
        weight_kg=float(weight_kg),
        total_estimated_cost=total_cost,
        estimated_delivery_days=total_days,
        route_legs=legs,
        path_nodes=path_nodes,
        path_summary=path_summary or build_path_summary(path_nodes),
        current_status=status,
        current_stage_index=stage_index,
        created_at=now,
        updated_at=now,
        estimated_arrival=estimated_arrival,
    )

    db.session.add(shipment)
    db.session.commit()
    return shipment


def get_shipment_by_tracking_number(tracking_number: str) -> Shipment | None:
    key = normalize_tracking_number(tracking_number)
    if not key:
        return None
    return Shipment.query.filter_by(tracking_number=key).first()


def get_shipment_by_id(shipment_id: int) -> Shipment | None:
    return db.session.get(Shipment, shipment_id)


def shipment_to_summary_dict(shipment: Shipment) -> dict[str, Any]:
    """Lightweight dict for APIs / future templates."""
    return {
        "id": shipment.id,
        "tracking_number": shipment.tracking_number,
        "origin_id": shipment.origin_id,
        "origin_name": shipment.origin_name,
        "destination_id": shipment.destination_id,
        "destination_name": shipment.destination_name,
        "direction_key": shipment.direction_key,
        "objective_key": shipment.objective_key,
        "objective_label": shipment.objective_label,
        "weight_kg": shipment.weight_kg,
        "total_estimated_cost": shipment.total_estimated_cost,
        "estimated_delivery_days": shipment.estimated_delivery_days,
        "path_summary": shipment.path_summary,
        "current_status": shipment.current_status,
        "current_stage_index": shipment.current_stage_index,
        "created_at": shipment.created_at.isoformat() if shipment.created_at else None,
        "updated_at": shipment.updated_at.isoformat() if shipment.updated_at else None,
        "estimated_arrival": shipment.estimated_arrival.isoformat()
        if shipment.estimated_arrival
        else None,
        "leg_count": len(shipment.route_legs or []),
    }
