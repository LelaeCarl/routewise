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


def _as_utc_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _effective_total_days(shipment: Shipment) -> float:
    """Planned transit duration used as the simulation timeline (days)."""
    t = float(shipment.estimated_delivery_days or 0.0)
    if t > 0:
        return t
    legs = shipment.route_legs or []
    s = sum(max(0.0, float(leg.get("time") or 0)) for leg in legs)
    if s > 0:
        return s
    return 1.0


def _normalized_leg_durations(legs: list[dict], total_days: float) -> list[float]:
    if not legs or total_days <= 0:
        return []
    raw = [max(0.0, float(leg.get("time") or 0)) for leg in legs]
    s = sum(raw)
    n = len(legs)
    if s > 0:
        scale = total_days / s
        return [t * scale for t in raw]
    return [total_days / n] * n


def _logistics_phases(derived_stage_index: int, is_delivered: bool) -> list[dict[str, Any]]:
    """Completed / current / upcoming for SHIPMENT_STATUSES based on simulated stage."""
    out: list[dict[str, Any]] = []
    for i, label in enumerate(SHIPMENT_STATUSES):
        if is_delivered:
            phase: Phase = "completed"
        elif i < derived_stage_index:
            phase = "completed"
        elif i == derived_stage_index:
            phase = "current"
        else:
            phase = "upcoming"
        out.append({"index": i, "status": label, "phase": phase})
    return out


def derive_shipment_progress(
    shipment: Shipment,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Simulate progress from elapsed wall time vs planned transit — no GPS, no background jobs.

    Deterministic: ``progress ≈ min(1, elapsed / estimated_total_days)``.
    Logistics status maps the first five stages to ``progress * 5`` buckets; **Delivered** when
    elapsed ≥ estimated journey time. Route legs (or path nodes) split the timeline using leg
    durations normalized to match ``estimated_delivery_days``.
    """
    now = datetime.now(timezone.utc) if now is None else _as_utc_aware(now)
    created = _as_utc_aware(shipment.created_at)
    total_days = _effective_total_days(shipment)

    elapsed_days = max(0.0, (now - created).total_seconds() / 86400.0)
    r = min(1.0, elapsed_days / total_days) if total_days > 0 else 0.0
    progress_percent = round(r * 100.0, 1)
    is_delivered = elapsed_days >= total_days - 1e-9 and total_days > 0

    if is_delivered:
        derived_stage_index = len(SHIPMENT_STATUSES) - 1
    else:
        derived_stage_index = min(4, int(r * 5.0))

    derived_status = SHIPMENT_STATUSES[derived_stage_index]

    legs: list[dict] = list(shipment.route_legs or [])
    pos = min(total_days, r * total_days) if not is_delivered else total_days

    route_rows: list[dict[str, Any]] = []
    current_leg_idx: int | None = None

    if legs:
        durations = _normalized_leg_durations(legs, total_days)
        boundaries = [0.0]
        for d in durations:
            boundaries.append(boundaries[-1] + d)

        for i, leg in enumerate(legs):
            lo = boundaries[i]
            hi = boundaries[i + 1]
            if is_delivered or pos >= hi - 1e-9:
                ph: Phase = "completed"
            elif lo <= pos < hi - 1e-9:
                ph = "current"
                current_leg_idx = i
            else:
                ph = "upcoming"
            route_rows.append({**_leg_display_row(leg, i), "phase": ph})
    else:
        nodes = list(shipment.path_nodes or [])
        if len(nodes) >= 2:
            nseg = len(nodes) - 1
            seg_days = total_days / nseg if nseg > 0 else total_days
            boundaries = [0.0]
            for _ in range(nseg):
                boundaries.append(boundaries[-1] + seg_days)
            for i in range(nseg):
                na = nodes[i]
                nb = nodes[i + 1]
                frm = str(na.get("name", ""))
                to = str(nb.get("name", ""))
                lo = boundaries[i]
                hi = boundaries[i + 1]
                if is_delivered or pos >= hi - 1e-9:
                    ph = "completed"
                elif lo <= pos < hi - 1e-9:
                    ph = "current"
                    current_leg_idx = i
                else:
                    ph = "upcoming"
                route_rows.append(
                    {
                        "leg_index": i,
                        "from_name": frm,
                        "to_name": to,
                        "mode": "Segment",
                        "mode_key": "segment",
                        "summary": f"{frm} → {to}",
                        "time": None,
                        "cost": None,
                        "phase": ph,
                    }
                )

    current_location_label = _derive_location_label(
        shipment,
        r=r,
        is_delivered=is_delivered,
        current_leg_idx=current_leg_idx,
        legs=legs,
    )

    status_milestones = _logistics_phases(derived_stage_index, is_delivered)

    return {
        "progress_percent": progress_percent,
        "progress_ratio": r,
        "elapsed_days": round(elapsed_days, 4),
        "estimated_total_days": total_days,
        "is_delivered": is_delivered,
        "derived_stage_index": derived_stage_index,
        "derived_status": derived_status,
        "current_location_label": current_location_label,
        "status_milestones": status_milestones,
        "route_milestones": route_rows,
        "simulation_note": "Progress is simulated from elapsed time versus the planned transit window (no live carrier data).",
    }


def _derive_location_label(
    shipment: Shipment,
    *,
    r: float,
    is_delivered: bool,
    current_leg_idx: int | None,
    legs: list[dict],
) -> str:
    if is_delivered:
        return f"Delivered — {shipment.destination_name}"
    if r < 0.02:
        return f"At origin hub — {shipment.origin_name}"
    if current_leg_idx is not None and 0 <= current_leg_idx < len(legs):
        leg = legs[current_leg_idx]
        to_n = (leg.get("to") or {}).get("name", "")
        frm_n = (leg.get("from") or {}).get("name", "")
        if to_n:
            return f"En route — toward {to_n}"
        if frm_n:
            return f"Departed — {frm_n}"
    return f"In transit — heading to {shipment.destination_name}"


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
