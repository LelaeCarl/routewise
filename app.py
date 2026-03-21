import os

from flask import Flask, render_template, request

from backend.comparison import (
    build_leg_labels,
    build_rationale,
    build_route_insight,
    build_route_story,
    enrich_alternatives,
)
from backend.data_loader import load_nodes
from backend.route_engine import RouteEngine


app = Flask(__name__)

def format_cny(value: float) -> str:
    """Format a numeric value as a realistic CNY currency string (no decimals)."""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    # Dataset values represent prototype shipment cost estimates in CNY.
    return f"¥{num:,.0f}"


def format_days(value: float) -> str:
    """Format transit time (days) with one decimal for readability."""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{num:.1f}"


_NODE_TYPE_LABELS = {
    "port": "Port",
    "airport": "Airport",
    "icd": "ICD",
    "rail_hub": "Rail hub",
    "road_hub": "Road hub",
}


def format_node_type(value: str) -> str:
    """Convert node type key to a human-readable label."""
    return _NODE_TYPE_LABELS.get(value, value)


# Make formatting available to all Jinja templates.
app.jinja_env.filters["format_cny"] = format_cny
app.jinja_env.filters["format_days"] = format_days
app.jinja_env.filters["format_node_type"] = format_node_type

PREFERENCE_LABELS = {
    "lowest_cost": "Lowest cost",
    "fastest_delivery": "Fastest delivery",
    "balanced_tradeoff": "Balanced trade-off",
}

DIRECTION_LABELS = {
    "china-kenya": "China → Kenya",
    "kenya-china": "Kenya → China",
}


OBJECTIVE_KEYS = ("lowest_cost", "fastest_delivery", "balanced_tradeoff")
LEGACY_OBJECTIVE_TO_OBJECTIVE = {
    "cheapest": "lowest_cost",
    "fastest": "fastest_delivery",
    "balanced": "balanced_tradeoff",
}


def _normalize_objective_key(obj_key: str) -> str:
    key = (obj_key or "").strip()
    if key in OBJECTIVE_KEYS:
        return key
    return LEGACY_OBJECTIVE_TO_OBJECTIVE.get(key, "balanced_tradeoff")


@app.route("/")
def index():
    return render_template("index.html", title="RouteWise")


@app.route("/planner")
def planner():
    nodes = load_nodes()

    allowed_types = {"port", "airport", "icd", "rail_hub", "road_hub"}

    china_nodes_raw = [n for n in nodes if n.country == "China" and n.type in allowed_types]
    kenya_nodes_raw = [n for n in nodes if n.country == "Kenya" and n.type in allowed_types]

    china_nodes = [{"id": n.id, "name": n.name, "city": n.city} for n in china_nodes_raw]
    kenya_nodes = [{"id": n.id, "name": n.name, "city": n.city} for n in kenya_nodes_raw]

    direction_key = request.args.get("direction", "china-kenya")
    origin_id = request.args.get("origin", "").strip()
    destination_id = request.args.get("destination", "").strip()
    weight = request.args.get("weight", "")
    preference_key = _normalize_objective_key(request.args.get("preference", "balanced_tradeoff"))

    direction_label = DIRECTION_LABELS.get(direction_key, "China → Kenya")
    preference_label = PREFERENCE_LABELS.get(preference_key, "Balanced")

    if direction_key == "china-kenya":
        origin_options = china_nodes_raw
        destination_options = kenya_nodes_raw
    else:
        origin_options = kenya_nodes_raw
        destination_options = china_nodes_raw

    origin_option_ids = {n.id for n in origin_options}
    destination_option_ids = {n.id for n in destination_options}

    origin_selected = origin_id if origin_id in origin_option_ids else (origin_options[0].id if origin_options else "")
    destination_selected = (
        destination_id if destination_id in destination_option_ids else (destination_options[0].id if destination_options else "")
    )

    return render_template(
        "planner.html",
        title="Plan Route",
        direction_key=direction_key,
        direction_label=direction_label,
        origin_selected=origin_selected,
        destination_selected=destination_selected,
        origin_options=origin_options,
        destination_options=destination_options,
        weight=weight,
        preference_key=preference_key,
        preference_label=preference_label,
        china_nodes=china_nodes,
        kenya_nodes=kenya_nodes,
    )


@app.route("/results")
def results():
    direction_key = request.args.get("direction", "china-kenya")
    preference_key = _normalize_objective_key(request.args.get("preference", "balanced_tradeoff"))

    origin_id = request.args.get("origin", "").strip()
    destination_id = request.args.get("destination", "").strip()
    weight = request.args.get("weight", "").strip()

    direction_label = DIRECTION_LABELS.get(direction_key, "China → Kenya")
    preference_label = PREFERENCE_LABELS.get(preference_key, "Balanced trade-off")

    nodes = load_nodes()
    node_map = {n.id: n for n in nodes}
    origin_name = node_map.get(origin_id).name if origin_id in node_map else origin_id
    destination_name = node_map.get(destination_id).name if destination_id in node_map else destination_id

    engine = RouteEngine()
    route = None
    alternatives = {}
    enriched_alts = {}
    route_insight = ""
    route_story = ""

    if not origin_id or not destination_id:
        route = {"success": False, "error": "Please select an origin and destination to generate a route analysis."}
    else:
        route = engine.compute_route(origin_id, destination_id, preference_key)
        for obj_key in OBJECTIVE_KEYS:
            alternatives[obj_key] = engine.compute_route(origin_id, destination_id, obj_key)

        if route.get("success"):
            route["route_rationale"] = build_rationale(route, preference_key, alternatives)
            route_insight = build_route_insight(route, preference_key)
            route_story = build_route_story(route)
            enriched_alts = enrich_alternatives(route, preference_key, alternatives)

            leg_labels = build_leg_labels(route)
            for i, label in enumerate(leg_labels):
                if i < len(route["legs"]):
                    route["legs"][i]["label"] = label

    return render_template(
        "results.html",
        title="Results",
        direction_key=direction_key,
        direction=direction_label,
        preference_key=preference_key,
        origin_id=origin_id,
        destination_id=destination_id,
        origin_name=origin_name,
        destination_name=destination_name,
        weight=weight,
        preference=preference_label,
        route=route,
        alternatives=enriched_alts if enriched_alts else alternatives,
        objective_label=preference_label,
        route_insight=route_insight,
        route_story=route_story,
    )


@app.route("/hubs")
def hubs():
    nodes = load_nodes()
    return render_template("hubs.html", title="Hubs", nodes=nodes)


@app.route("/about")
def about():
    return render_template("about.html", title="About")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)

