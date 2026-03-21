"""Decision intelligence layer for route recommendations.

Analyzes route results to produce:
- Classification tags (cost-efficient, time-optimized, balanced, similar-options)
- Recommendation insights using real comparison data
- Trade-off explanations with cost-per-day-saved metrics
- Efficiency metrics for decision support

Similarity thresholds match those in comparison.py:
- Cost spread under 5% → considered minor
- Time spread under 1.0 day → considered minor
"""

from __future__ import annotations

COST_SIMILAR_PCT = 5.0
TIME_SIMILAR_DAYS = 1.0

CLASSIFICATION_LABELS = {
    "cost-efficient": "Cost-efficient",
    "time-optimized": "Time-optimized",
    "balanced": "Balanced",
    "similar-options": "Similar options",
}

_BEST_FOR = {
    "lowest_cost": "Best for: minimizing cost",
    "fastest_delivery": "Best for: fastest delivery",
    "balanced_tradeoff": "Best for: balanced planning",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _successful(alternatives: dict) -> dict:
    return {k: v for k, v in alternatives.items() if v.get("success")}


def _all_similar(alternatives: dict) -> bool:
    """All successful alternatives produce nearly identical results."""
    ok = list(_successful(alternatives).values())
    if len(ok) < 2:
        return True

    costs = [r["total_cost"] for r in ok]
    times = [r["total_time"] for r in ok]

    avg_cost = sum(costs) / len(costs)
    cost_spread_pct = ((max(costs) - min(costs)) / avg_cost * 100) if avg_cost > 0 else 0
    time_spread = max(times) - min(times)

    return cost_spread_pct < COST_SIMILAR_PCT and time_spread < TIME_SIMILAR_DAYS


def _get_extremes(alternatives: dict) -> dict | None:
    """Find cheapest and fastest among successful alternatives."""
    ok = _successful(alternatives)
    if len(ok) < 2:
        return None

    cheapest_key = min(ok, key=lambda k: ok[k]["total_cost"])
    fastest_key = min(ok, key=lambda k: ok[k]["total_time"])

    return {
        "cheapest_key": cheapest_key,
        "cheapest": ok[cheapest_key],
        "fastest_key": fastest_key,
        "fastest": ok[fastest_key],
    }


def _near(a: dict, b: dict) -> bool:
    """Two routes are near-identical."""
    if b["total_cost"] == 0:
        return True
    cost_pct = abs(a["total_cost"] - b["total_cost"]) / b["total_cost"] * 100
    time_diff = abs(a["total_time"] - b["total_time"])
    return cost_pct < COST_SIMILAR_PCT and time_diff < TIME_SIMILAR_DAYS


# ---------------------------------------------------------------------------
# 2.1  Efficiency metrics
# ---------------------------------------------------------------------------

def compute_efficiency_metrics(alternatives: dict) -> dict:
    """Cost-per-day-saved between the cheapest and fastest routes.

    Returns empty dict when there is no meaningful speed premium.
    """
    ext = _get_extremes(alternatives)
    if not ext:
        return {}

    cheapest, fastest = ext["cheapest"], ext["fastest"]

    cost_diff = fastest["total_cost"] - cheapest["total_cost"]
    days_saved = cheapest["total_time"] - fastest["total_time"]

    cost_per_day = (cost_diff / days_saved) if days_saved > 0.01 else 0.0

    return {
        "cost_diff": cost_diff,
        "days_saved": days_saved,
        "cost_per_day_saved": round(cost_per_day, 0),
        "cheapest_cost": cheapest["total_cost"],
        "cheapest_time": cheapest["total_time"],
        "fastest_cost": fastest["total_cost"],
        "fastest_time": fastest["total_time"],
    }


# ---------------------------------------------------------------------------
# 2.2  Classification
# ---------------------------------------------------------------------------

def classify_route(current_route: dict, objective_key: str, alternatives: dict) -> str:
    """Classify the current route relative to alternatives.

    Returns one of: cost-efficient, time-optimized, balanced, similar-options.
    """
    if not current_route.get("success"):
        return "balanced"

    if _all_similar(alternatives):
        return "similar-options"

    ok = _successful(alternatives)
    if not ok:
        return "balanced"

    min_cost = min(v["total_cost"] for v in ok.values())
    min_time = min(v["total_time"] for v in ok.values())

    is_cheapest = current_route["total_cost"] <= min_cost * 1.001
    is_fastest = current_route["total_time"] <= min_time * 1.001

    if is_cheapest and is_fastest:
        return "cost-efficient"
    if is_cheapest:
        return "cost-efficient"
    if is_fastest:
        return "time-optimized"
    return "balanced"


# ---------------------------------------------------------------------------
# 2.3  Decision insight
# ---------------------------------------------------------------------------

def build_decision_insight(
    current_route: dict, objective_key: str, alternatives: dict
) -> str:
    """1-2 sentence recommendation insight using real computed data."""
    if not current_route.get("success"):
        return ""

    if _all_similar(alternatives):
        return (
            "All routing objectives produce similar outcomes for this corridor, "
            "indicating minimal trade-offs regardless of which objective you choose."
        )

    ext = _get_extremes(alternatives)
    if not ext:
        return ""

    cheapest, fastest = ext["cheapest"], ext["fastest"]
    cost_diff = fastest["total_cost"] - cheapest["total_cost"]
    days_saved = cheapest["total_time"] - fastest["total_time"]

    if objective_key == "lowest_cost":
        return _insight_cost(current_route, cost_diff, days_saved)
    if objective_key == "fastest_delivery":
        return _insight_speed(current_route, cost_diff, days_saved)
    return _insight_balanced(current_route, cheapest, fastest, cost_diff, days_saved)


def _insight_cost(route: dict, cost_diff: float, days_saved: float) -> str:
    if days_saved > TIME_SIMILAR_DAYS:
        return (
            f"This route minimizes cost while staying within "
            f"{days_saved:.1f} days of the fastest option. "
            f"Choosing speed instead would add \u00a5{cost_diff:,.0f} to the shipment."
        )
    return (
        "This route achieves the lowest cost with transit time "
        "comparable to faster alternatives."
    )


def _insight_speed(route: dict, cost_diff: float, days_saved: float) -> str:
    if days_saved > TIME_SIMILAR_DAYS and cost_diff > 0:
        return (
            f"The fastest route saves {days_saved:.1f} days but costs "
            f"\u00a5{cost_diff:,.0f} more than the cheapest option, "
            f"making it suitable for time-sensitive shipments."
        )
    return (
        "This route delivers the shortest transit time "
        "with a manageable cost premium."
    )


def _insight_balanced(
    route: dict,
    cheapest: dict,
    fastest: dict,
    cost_diff: float,
    days_saved: float,
) -> str:
    near_fastest = _near(route, fastest)
    near_cheapest = _near(route, cheapest)

    if near_cheapest and near_fastest:
        return "All objectives converge on the same route for this corridor."

    if near_fastest:
        return (
            "The balanced analysis favors speed for this corridor, "
            "producing a route close to the fastest option."
        )

    if near_cheapest:
        return (
            "The balanced analysis favors economy for this corridor, "
            "producing a route close to the lowest-cost option."
        )

    over_cheap = route["total_cost"] - cheapest["total_cost"]
    faster_than_cheap = cheapest["total_time"] - route["total_time"]

    return (
        f"This route offers a practical balance \u2014 "
        f"\u00a5{over_cheap:,.0f} more than the cheapest option "
        f"but {faster_than_cheap:.1f} days faster."
    )


# ---------------------------------------------------------------------------
# 2.4  Trade-off explanation
# ---------------------------------------------------------------------------

def build_tradeoff_explanation(alternatives: dict) -> str:
    """Short trade-off sentence using cost-per-day-saved metric."""
    if _all_similar(alternatives):
        return "Differences between objectives are minimal for this route pair."

    m = compute_efficiency_metrics(alternatives)
    if not m or m["days_saved"] <= 0.01:
        return ""

    cpd = m["cost_per_day_saved"]
    cost = m["cost_diff"]
    days = m["days_saved"]

    if cpd <= 0:
        return ""

    if cost < 1000:
        return (
            f"Minimal cost difference (\u00a5{cost:,.0f}) for "
            f"{days:.1f} days improvement."
        )

    if cpd > 3000:
        return (
            f"Faster delivery costs approximately \u00a5{cpd:,.0f} per day saved, "
            f"a significant premium."
        )

    return (
        f"You pay approximately \u00a5{cpd:,.0f} per day saved "
        f"when choosing the faster route."
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def build_decision_context(
    current_route: dict, objective_key: str, alternatives: dict
) -> dict:
    """Produce all decision intelligence data for template rendering.

    Returns a single dict with:
      insight              – recommendation sentence
      tradeoff             – cost-per-day explanation
      classification       – tag key
      classification_label – display label
      metrics              – efficiency metrics dict
      all_similar          – bool
      best_for             – dict mapping objective keys to 'Best for' labels
    """
    if not current_route.get("success"):
        return {
            "insight": "",
            "tradeoff": "",
            "classification": "balanced",
            "classification_label": "Balanced",
            "metrics": {},
            "all_similar": False,
            "best_for": {},
        }

    similar = _all_similar(alternatives)

    return {
        "insight": build_decision_insight(current_route, objective_key, alternatives),
        "tradeoff": build_tradeoff_explanation(alternatives),
        "classification": classify_route(current_route, objective_key, alternatives),
        "classification_label": CLASSIFICATION_LABELS.get(
            classify_route(current_route, objective_key, alternatives),
            "Balanced",
        ),
        "metrics": compute_efficiency_metrics(alternatives),
        "all_similar": similar,
        "best_for": {k: _BEST_FOR.get(k, "") for k in alternatives},
    }
