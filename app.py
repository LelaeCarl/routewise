import os

from flask import Flask, render_template, request

from backend.data_loader import load_network


app = Flask(__name__)


PREFERENCE_LABELS = {
    "cheapest": "Cheapest",
    "fastest": "Fastest",
    "balanced": "Balanced",
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
    direction_key = request.args.get("direction", "china-kenya")
    origin = request.args.get("origin", "")
    destination = request.args.get("destination", "")
    weight = request.args.get("weight", "")
    preference_key = request.args.get("preference", "balanced")

    direction_label = DIRECTION_LABELS.get(direction_key, "China → Kenya")
    preference_label = PREFERENCE_LABELS.get(preference_key, "Balanced")

    return render_template(
        "planner.html",
        title="Plan Route",
        direction_key=direction_key,
        direction_label=direction_label,
        origin=origin,
        destination=destination,
        weight=weight,
        preference_key=preference_key,
        preference_label=preference_label,
    )


@app.route("/results")
def results():
    direction_key = request.args.get("direction", "china-kenya")
    preference_key = request.args.get("preference", "balanced")

    origin = request.args.get("origin", "").strip()
    destination = request.args.get("destination", "").strip()
    weight = request.args.get("weight", "").strip()

    direction_label = DIRECTION_LABELS.get(direction_key, "China → Kenya")
    preference_label = PREFERENCE_LABELS.get(preference_key, "Balanced")

    kpis = _placeholder_kpis(preference_key)
    modes_list = [m.strip() for m in kpis["modes"].split("+") if m.strip()]

    return render_template(
        "results.html",
        title="Results",
        direction_key=direction_key,
        direction=direction_label,
        preference_key=preference_key,
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

