"""Route comparison and decision explanation utilities.

Computes deltas between route results and generates human-readable
summaries to help users understand trade-offs between routing objectives.

Similarity thresholds are intentionally simple and explainable:
- Cost difference under 5% of the current route's cost → considered minor
- Time difference under 1.0 day → considered minor
"""

from __future__ import annotations

COST_SIMILAR_PCT = 5.0
TIME_SIMILAR_DAYS = 1.0

OBJECTIVE_LABELS = {
    "lowest_cost": "Lowest cost",
    "fastest_delivery": "Fastest delivery",
    "balanced_tradeoff": "Balanced trade-off",
}


def compute_delta(current: dict, alternative: dict) -> dict:
    """Compute cost and time differences between current route and an alternative.

    Returns a dict with:
      cost_delta: alternative cost minus current cost (positive = alt is more expensive)
      time_delta: alternative time minus current time (positive = alt is slower)
      cost_pct:   cost_delta as a percentage of the current route's cost
    """
    cost_delta = alternative["total_cost"] - current["total_cost"]
    time_delta = alternative["total_time"] - current["total_time"]

    cost_pct = (cost_delta / current["total_cost"] * 100) if current["total_cost"] > 0 else 0.0

    return {
        "cost_delta": cost_delta,
        "time_delta": time_delta,
        "cost_pct": cost_pct,
    }


def _is_similar(delta: dict) -> bool:
    """Two routes are considered similar when both cost and time differences are minor."""
    return abs(delta["cost_pct"]) < COST_SIMILAR_PCT and abs(delta["time_delta"]) < TIME_SIMILAR_DAYS


def format_delta_cost(value: float) -> str:
    """Format a cost delta: '+¥600' or '−¥1,200'."""
    sign = "+" if value >= 0 else "\u2212"
    return f"{sign}\u00a5{abs(value):,.0f}"


def format_delta_time(value: float) -> str:
    """Format a time delta: '+1.2 d' or '−3.0 d'."""
    sign = "+" if value >= 0 else "\u2212"
    return f"{sign}{abs(value):.1f} d"


def comparison_summary(delta: dict) -> str:
    """Generate a short human-readable comparison of an alternative vs the current route.

    Examples:
      "Very similar cost and transit time"
      "¥600 cheaper, 1.2 days slower"
      "¥2,100 more, 3.0 days faster"
    """
    if _is_similar(delta):
        return "Very similar cost and transit time"

    cost_d = delta["cost_delta"]
    time_d = delta["time_delta"]
    cost_minor = abs(delta["cost_pct"]) < COST_SIMILAR_PCT
    time_minor = abs(time_d) < TIME_SIMILAR_DAYS

    if cost_minor:
        cost_part = "similar cost"
    elif cost_d < 0:
        cost_part = f"\u00a5{abs(cost_d):,.0f} cheaper"
    else:
        cost_part = f"\u00a5{abs(cost_d):,.0f} more"

    if time_minor:
        time_part = "similar time"
    elif time_d < 0:
        time_part = f"{abs(time_d):.1f} days faster"
    else:
        time_part = f"{abs(time_d):.1f} days slower"

    return f"{cost_part}, {time_part}"


def comparison_tag(delta: dict) -> str:
    """Return a short tag for the alternative: 'cheaper', 'faster', 'similar', or 'trade-off'."""
    if _is_similar(delta):
        return "similar"

    cost_better = delta["cost_delta"] < 0 and abs(delta["cost_pct"]) >= COST_SIMILAR_PCT
    time_better = delta["time_delta"] < 0 and abs(delta["time_delta"]) >= TIME_SIMILAR_DAYS

    if cost_better and time_better:
        return "cheaper"
    if cost_better:
        return "cheaper"
    if time_better:
        return "faster"
    return "trade-off"


def build_rationale(current_route: dict, objective_key: str, alternatives: dict) -> str:
    """Generate a comparison-aware 'Why this route' explanation.

    Uses actual delta data from the alternatives to produce a concrete
    explanation rather than a generic objective description.
    """
    if not current_route.get("success"):
        return "Route computation was unsuccessful."

    modes = ", ".join(current_route.get("modes_used", [])) or "direct"

    other_keys = [k for k in alternatives if k != objective_key and alternatives[k].get("success")]
    if not other_keys:
        return _fallback_rationale(current_route, objective_key, modes)

    deltas = {k: compute_delta(current_route, alternatives[k]) for k in other_keys}

    if objective_key == "lowest_cost":
        return _rationale_lowest_cost(current_route, deltas, modes)
    if objective_key == "fastest_delivery":
        return _rationale_fastest(current_route, deltas, modes)
    return _rationale_balanced(current_route, deltas, modes)


def _fallback_rationale(route: dict, objective_key: str, modes: str) -> str:
    if objective_key == "lowest_cost":
        return f"This route minimizes total estimated cost using {modes} transport."
    if objective_key == "fastest_delivery":
        return f"This route minimizes estimated transit time using {modes} transport."
    return f"This route balances cost and time using {modes} transport."


def _rationale_lowest_cost(route: dict, deltas: dict, modes: str) -> str:
    fd = deltas.get("fastest_delivery")
    if fd and not _is_similar(fd):
        if fd["cost_delta"] > 0 and fd["time_delta"] < 0:
            return (
                f"This route offers the lowest estimated cost at \u00a5{route['total_cost']:,.0f}. "
                f"The fastest alternative is {abs(fd['time_delta']):.1f} days quicker "
                f"but costs \u00a5{abs(fd['cost_delta']):,.0f} more."
            )
        if fd["cost_delta"] > 0:
            return (
                f"This route offers the lowest estimated cost at \u00a5{route['total_cost']:,.0f}. "
                f"The fastest alternative costs \u00a5{abs(fd['cost_delta']):,.0f} more "
                f"with comparable transit time."
            )
    return (
        f"This route minimizes total estimated cost at \u00a5{route['total_cost']:,.0f}. "
        f"The alternatives produce very similar results for this route pair."
    )


def _rationale_fastest(route: dict, deltas: dict, modes: str) -> str:
    lc = deltas.get("lowest_cost")
    if lc and not _is_similar(lc):
        if lc["cost_delta"] < 0 and lc["time_delta"] > 0:
            return (
                f"This route minimizes estimated transit time at {route['total_time']:.1f} days. "
                f"The cheapest alternative saves \u00a5{abs(lc['cost_delta']):,.0f} "
                f"but takes {abs(lc['time_delta']):.1f} days longer."
            )
        if lc["cost_delta"] < 0:
            return (
                f"This route minimizes estimated transit time at {route['total_time']:.1f} days. "
                f"The cheapest alternative saves \u00a5{abs(lc['cost_delta']):,.0f} "
                f"with comparable transit time."
            )
    return (
        f"This route minimizes estimated transit time at {route['total_time']:.1f} days. "
        f"The alternatives produce very similar results for this route pair."
    )


def _rationale_balanced(route: dict, deltas: dict, modes: str) -> str:
    lc = deltas.get("lowest_cost")
    fd = deltas.get("fastest_delivery")

    if lc and fd:
        lc_similar = _is_similar(lc)
        fd_similar = _is_similar(fd)

        if lc_similar and fd_similar:
            return (
                f"This route balances cost and time. "
                f"All objectives produce similar results for this route pair."
            )

        pieces = []
        if not lc_similar and lc["cost_delta"] < 0:
            pieces.append(
                f"the cheapest option saves \u00a5{abs(lc['cost_delta']):,.0f} "
                f"but takes {abs(lc['time_delta']):.1f} days longer"
            )
        if not fd_similar and fd["time_delta"] < 0:
            pieces.append(
                f"the fastest option is {abs(fd['time_delta']):.1f} days quicker "
                f"but costs \u00a5{abs(fd['cost_delta']):,.0f} more"
            )

        if pieces:
            joined = "; ".join(pieces)
            return f"This route offers a practical middle ground. {joined[0].upper()}{joined[1:]}."

    return (
        f"This route balances cost (\u00a5{route['total_cost']:,.0f}) "
        f"and transit time ({route['total_time']:.1f} days), "
        f"offering a middle ground between the cheapest and fastest options."
    )


def build_route_insight(current_route: dict, objective_key: str) -> str:
    """Generate a short insight sentence about the route's transport structure."""
    if not current_route.get("success") or not current_route.get("legs"):
        return ""

    modes = current_route.get("modes_used", [])
    legs = current_route.get("legs", [])
    total_cost = current_route.get("total_cost", 0)

    if not modes or total_cost == 0:
        return ""

    if len(modes) == 1:
        m = modes[0].lower()
        if objective_key == "lowest_cost":
            return f"Uses a single {m} leg, keeping costs minimal with direct transport."
        if objective_key == "fastest_delivery":
            return f"Uses a single {m} leg for the fastest available transit."
        return f"Uses a single {m} leg, balancing cost and time efficiently."

    mode_costs = {}
    for leg in legs:
        mode_costs[leg["mode"]] = mode_costs.get(leg["mode"], 0) + leg.get("cost", 0)

    dominant_mode = max(mode_costs, key=mode_costs.get)
    dominant_pct = mode_costs[dominant_mode] / total_cost * 100

    if dominant_pct > 60:
        return (
            f"The {dominant_mode.lower()} segment carries {dominant_pct:.0f}% of total cost, "
            f"making it the primary corridor in this route."
        )

    return f"Combines {', '.join(m.lower() for m in modes)} transport across {len(legs)} legs."


def enrich_alternatives(current_route: dict, objective_key: str, alternatives: dict) -> dict:
    """Add comparison data to each alternative for template rendering.

    Each alternative entry gets:
      is_current: bool
      delta: dict or None
      summary: human-readable comparison string
      tag: short label ('cheaper', 'faster', 'similar', 'trade-off', 'current')
      delta_cost_fmt: formatted cost delta string
      delta_time_fmt: formatted time delta string
    """
    enriched = {}

    for obj_key, alt in alternatives.items():
        entry = dict(alt)

        if obj_key == objective_key:
            entry["is_current"] = True
            entry["delta"] = None
            entry["summary"] = "Currently selected"
            entry["tag"] = "current"
            entry["delta_cost_fmt"] = ""
            entry["delta_time_fmt"] = ""
        elif alt.get("success") and current_route.get("success"):
            delta = compute_delta(current_route, alt)
            entry["is_current"] = False
            entry["delta"] = delta
            entry["summary"] = comparison_summary(delta)
            entry["tag"] = comparison_tag(delta)
            entry["delta_cost_fmt"] = format_delta_cost(delta["cost_delta"])
            entry["delta_time_fmt"] = format_delta_time(delta["time_delta"])
        else:
            entry["is_current"] = False
            entry["delta"] = None
            entry["summary"] = ""
            entry["tag"] = ""
            entry["delta_cost_fmt"] = ""
            entry["delta_time_fmt"] = ""

        enriched[obj_key] = entry

    return enriched
