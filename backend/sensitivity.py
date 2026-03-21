"""Weight sensitivity analysis for route recommendations.

Evaluates how the recommended route changes across a range of shipment
weights, detecting breakpoints where the optimal route shifts between
transport modes.

The approach is scenario-based: compute the route at a small fixed set
of representative weights, compare the resulting paths, and report any
shifts.  This is intentionally simple and academically explainable —
no interpolation or continuous optimization is performed.
"""

from __future__ import annotations

SAMPLE_WEIGHTS = [10, 100, 500, 1000, 5000]


def _route_fingerprint(route: dict) -> tuple:
    """Hashable identifier for the path taken."""
    if not route.get("success"):
        return ()
    return tuple(route.get("path_node_ids", []))


def _modes_label(route: dict) -> str:
    modes = route.get("modes_used", [])
    return ", ".join(modes) if modes else "\u2014"


def _fmt_weight(w: float) -> str:
    return f"{w:,.0f} kg"


# ---------------------------------------------------------------------------
# 2.1  Weight scenarios
# ---------------------------------------------------------------------------

def analyze_weight_scenarios(
    origin_id: str,
    destination_id: str,
    objective_key: str,
    current_weight: float,
    engine,
) -> list[dict]:
    """Compute route outcomes at representative weights.

    The current_weight is included alongside the fixed sample set so
    the user can see exactly where their shipment sits.
    """
    weights = sorted(set(SAMPLE_WEIGHTS) | {current_weight})

    results: list[dict] = []
    for w in weights:
        route = engine.compute_route(origin_id, destination_id, objective_key, float(w))
        if not route.get("success"):
            continue
        results.append({
            "weight": w,
            "weight_label": _fmt_weight(w),
            "total_cost": route["total_cost"],
            "total_time": route["total_time"],
            "modes": route["modes_used"],
            "modes_label": _modes_label(route),
            "fingerprint": _route_fingerprint(route),
            "is_current": (w == current_weight),
        })
    return results


# ---------------------------------------------------------------------------
# 2.2  Breakpoint detection
# ---------------------------------------------------------------------------

def detect_breakpoint(scenarios: list[dict]) -> dict:
    """Detect whether the recommended route changes across tested weights.

    Returns a dict with:
      shift_detected  – bool
      summary         – human-readable sentence
      breakpoint_low  – lower weight of first shift (or None)
      breakpoint_high – upper weight of first shift (or None)
    """
    if len(scenarios) < 2:
        return {
            "shift_detected": False,
            "summary": "Insufficient data to analyse weight sensitivity.",
            "breakpoint_low": None,
            "breakpoint_high": None,
        }

    shifts: list[tuple] = []
    for i in range(1, len(scenarios)):
        prev, curr = scenarios[i - 1], scenarios[i]
        if prev["fingerprint"] != curr["fingerprint"]:
            shifts.append((
                prev["weight"], curr["weight"],
                prev["modes_label"], curr["modes_label"],
            ))

    if not shifts:
        modes = scenarios[0]["modes_label"]
        return {
            "shift_detected": False,
            "summary": (
                f"The recommended route stays consistent ({modes}) "
                f"across the tested weight range."
            ),
            "breakpoint_low": None,
            "breakpoint_high": None,
        }

    low, high, from_modes, to_modes = shifts[0]

    if len(shifts) == 1:
        summary = (
            f"Route preference shifts between {_fmt_weight(low)} and "
            f"{_fmt_weight(high)}: {from_modes} gives way to {to_modes}."
        )
    else:
        summary = (
            f"Multiple route changes detected across the weight range. "
            f"The first shift occurs between {_fmt_weight(low)} and "
            f"{_fmt_weight(high)}."
        )

    return {
        "shift_detected": True,
        "summary": summary,
        "breakpoint_low": low,
        "breakpoint_high": high,
    }


# ---------------------------------------------------------------------------
# 2.3  Weight insight
# ---------------------------------------------------------------------------

def build_weight_insight(
    current_route: dict,
    scenarios: list[dict],
    breakpoint_info: dict,
) -> str:
    """Short human-readable sentence about weight sensitivity."""
    if not current_route.get("success") or not scenarios:
        return ""

    if not breakpoint_info.get("shift_detected"):
        modes = current_route.get("modes_used", [])
        m = ", ".join(m.lower() for m in modes) if modes else "direct"
        return (
            f"This {m} route remains the recommended option "
            f"across the tested shipment range."
        )

    low_modes = set(scenarios[0]["modes"])
    high_modes = set(scenarios[-1]["modes"])

    if "Air" in low_modes and "Sea" in high_modes:
        return (
            "This recommendation is weight-sensitive: air is competitive "
            "at low shipment weights, but sea becomes more economical "
            "as cargo size grows."
        )

    if "Air" in low_modes:
        return (
            "Air transport is favored at lighter weights. "
            "The route composition changes as shipment weight increases."
        )

    return (
        "The recommended route varies with shipment weight, "
        "reflecting different cost structures across transport modes."
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def build_sensitivity_context(
    origin_id: str,
    destination_id: str,
    objective_key: str,
    current_weight: float,
    current_route: dict,
    engine,
) -> dict:
    """Produce all sensitivity data for template rendering.

    Returns a single dict with:
      scenarios      – list of weight scenario dicts
      shift_detected – bool
      shift_summary  – human-readable shift description
      insight        – short weight-sensitivity sentence
    """
    if not current_route.get("success"):
        return {
            "scenarios": [],
            "shift_detected": False,
            "shift_summary": "",
            "insight": "",
        }

    scenarios = analyze_weight_scenarios(
        origin_id, destination_id, objective_key, current_weight, engine,
    )
    bp = detect_breakpoint(scenarios)

    return {
        "scenarios": scenarios,
        "shift_detected": bp["shift_detected"],
        "shift_summary": bp["summary"],
        "insight": build_weight_insight(current_route, scenarios, bp),
    }
