import os

from flask import Flask, render_template, request

from backend.data_loader import load_network, load_nodes


app = Flask(__name__)


PREFERENCE_LABELS = {
    "cheapest": "Lowest cost",
    "fastest": "Fastest delivery",
    "balanced": "Balanced trade-off",
}

DIRECTION_LABELS = {
    "china-kenya": "China → Kenya",
    "kenya-china": "Kenya → China",
}


def _placeholder_kpis(preference_key: str) -> dict:
    # Phase 1: deterministic placeholders keyed off preference only.
    # This keeps the scaffold realistic without implementing the routing algorithm.
    mapping = {
        "cheapest": {
            "cost": "$1,240",
            "time": "19 days",
            "route_type": "Cost-Optimized",
            "modes": "Sea + Road",
        },
        "fastest": {
            "cost": "$1,680",
            "time": "12 days",
            "route_type": "Time-Optimized",
            "modes": "Air + Road",
        },
        "balanced": {
            "cost": "$1,420",
            "time": "15 days",
            "route_type": "Balanced Trade-off",
            "modes": "Sea + Rail + Road",
        },
    }
    return mapping.get(preference_key, mapping["balanced"])


@app.route("/")
def index():
    return render_template("index.html", title="RouteWise")


@app.route("/planner")
def planner():
    nodes = load_nodes()

    allowed_origin_destination_types = {"port", "airport", "icd", "rail_hub", "road_hub"}

    direction_key = request.args.get("direction", "china-kenya")
    origin_id = request.args.get("origin", "").strip()
    destination_id = request.args.get("destination", "").strip()
    weight = request.args.get("weight", "")
    preference_key = request.args.get("preference", "balanced")

    direction_label = DIRECTION_LABELS.get(direction_key, "China → Kenya")
    preference_label = PREFERENCE_LABELS.get(preference_key, "Balanced")

    if direction_key == "china-kenya":
        origin_options = [n for n in nodes if n.country == "China" and n.type in allowed_origin_destination_types]
        destination_options = [
            n for n in nodes if n.country == "Kenya" and n.type in allowed_origin_destination_types
        ]
    else:
        origin_options = [n for n in nodes if n.country == "Kenya" and n.type in allowed_origin_destination_types]
        destination_options = [
            n for n in nodes if n.country == "China" and n.type in allowed_origin_destination_types
        ]

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
    )


@app.route("/results")
def results():
    direction_key = request.args.get("direction", "china-kenya")
    preference_key = request.args.get("preference", "balanced")

    origin_id = request.args.get("origin", "").strip()
    destination_id = request.args.get("destination", "").strip()
    weight = request.args.get("weight", "").strip()

    direction_label = DIRECTION_LABELS.get(direction_key, "China → Kenya")
    preference_label = PREFERENCE_LABELS.get(preference_key, "Balanced")

    kpis = _placeholder_kpis(preference_key)
    modes_list = [m.strip() for m in kpis["modes"].split("+") if m.strip()]

    nodes = load_nodes()
    node_map = {n.id: n for n in nodes}
    origin = node_map.get(origin_id).name if origin_id in node_map else origin_id
    destination = node_map.get(destination_id).name if destination_id in node_map else destination_id

    return render_template(
        "results.html",
        title="Results",
        direction_key=direction_key,
        direction=direction_label,
        preference_key=preference_key,
        origin_id=origin_id,
        destination_id=destination_id,
        origin=origin,
        destination=destination,
        weight=weight,
        preference=preference_label,
        kpis=kpis,
        modes_list=modes_list,
    )


@app.route("/hubs")
def hubs():
    nodes, _edges = load_network()
    return render_template("hubs.html", title="Hubs", nodes=nodes)


@app.route("/about")
def about():
    return render_template("about.html", title="About")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)

