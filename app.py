import os

import click
from flask import Flask, flash, g, redirect, render_template, request, session, url_for
from sqlalchemy import or_
from sqlalchemy.exc import OperationalError

from backend.comparison import (
    build_leg_labels,
    build_rationale,
    build_route_insight,
    build_route_story,
    enrich_alternatives,
)
from backend.data_loader import load_nodes
from backend.decision import build_decision_context
from backend.route_engine import RouteEngine
from backend.sensitivity import build_sensitivity_context
from backend.extensions import db
from backend.db_models import RouteAnalysis, User
from backend.auth_routes import auth_bp
from backend.admin_routes import admin_bp
from backend.auth_utils import login_required


app = Flask(__name__)

# --- Core config (local dev defaults) ---
app.secret_key = os.environ.get("ROUTEWISE_SECRET_KEY", "dev-routewise-secret-change-me")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL",
    "sqlite:///routewise.db",
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

# Register route groups
app.register_blueprint(auth_bp)
app.register_blueprint(admin_bp)


@app.cli.command("init-db")
def init_db_command():
    """Initialize SQLite tables."""
    with app.app_context():
        db.create_all()
    print("Initialized database tables.")


@app.cli.command("seed-admin")
@click.option(
    "--force",
    is_flag=True,
    help="If an admin already exists, reset username, email, and password from env (or dev defaults).",
)
def seed_admin_command(force: bool) -> None:
    """Seed a local dev admin account, or reset it with --force when login no longer works."""
    with app.app_context():
        db.create_all()

        username = os.environ.get("ROUTEWISE_ADMIN_USERNAME", "carl")
        email = os.environ.get("ROUTEWISE_ADMIN_EMAIL", "admin@routewise.local").lower()
        password = os.environ.get("ROUTEWISE_ADMIN_PASSWORD", "carl123")

        existing = User.query.filter_by(role="admin").first()
        if existing:
            if not force:
                print("Admin already exists. Skipping seed. Use --force to reset password.")
                return
            existing.username = username
            existing.email = email
            existing.set_password(password)
            db.session.commit()
            print(f"Reset dev admin: username={username!r} email={email!r} (password from env or default).")
            return

        user = User(username=username, email=email, role="admin")
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        print(f"Seeded admin user '{username}' ({email}).")


@app.before_request
def load_current_user():
    # Make local development resilient if the DB hasn't been initialized yet.
    try:
        db.create_all()
    except OperationalError:
        # If the DB file can't be created or opened, continue without auth state.
        g.user = None
        return

    user_id = session.get("user_id")
    try:
        g.user = User.query.get(user_id) if user_id else None
    except OperationalError:
        g.user = None


@app.before_request
def enforce_login_gate():
    """
    Hard gate: RouteWise behaves as a login-required application.
    Any unauthenticated request to non-auth endpoints is redirected to /login?next=...
    """
    if getattr(g, "user", None):
        return None

    endpoint = request.endpoint or ""
    if endpoint == "static":
        return None
    if endpoint.startswith("auth."):
        return None

    nxt = request.full_path or request.path or "/"
    if nxt.endswith("?"):
        nxt = nxt[:-1]
    return redirect(url_for("auth.login", next=nxt))


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
    "practical_route": "Practical option",
}

DIRECTION_LABELS = {
    "china-kenya": "China → Kenya",
    "kenya-china": "Kenya → China",
}


OBJECTIVE_KEYS = ("lowest_cost", "fastest_delivery", "practical_route")
LEGACY_OBJECTIVE_TO_OBJECTIVE = {
    "cheapest": "lowest_cost",
    "fastest": "fastest_delivery",
    "balanced": "practical_route",
}


def _normalize_objective_key(obj_key: str) -> str:
    key = (obj_key or "").strip()
    if key in OBJECTIVE_KEYS:
        return key
    return LEGACY_OBJECTIVE_TO_OBJECTIVE.get(key, "practical_route")


@app.context_processor
def inject_user():
    return {
        "current_user": getattr(g, "user", None),
        "is_admin": bool(getattr(getattr(g, "user", None), "is_admin", False)),
        "preference_labels": PREFERENCE_LABELS,
    }


@app.route("/")
def index():
    return redirect(url_for("home"))


@app.route("/home")
@login_required
def home():
    user = g.user
    recent = (
        RouteAnalysis.query.filter_by(user_id=user.id)
        .order_by(RouteAnalysis.created_at.desc())
        .limit(6)
        .all()
    )
    analyses_total = RouteAnalysis.query.filter_by(user_id=user.id).count()
    return render_template(
        "home.html",
        title="Workspace",
        recent_analyses=recent,
        analyses_total=analyses_total,
    )


@app.route("/analyses")
@login_required
def analyses():
    items = (
        RouteAnalysis.query.filter_by(user_id=g.user.id)
        .order_by(RouteAnalysis.created_at.desc())
        .all()
    )
    return render_template("analyses.html", title="Recent analyses", analyses=items)


@app.route("/planner")
def planner():
    nodes = load_nodes()

    allowed_types = {"port", "airport", "icd", "rail_hub", "road_hub"}

    china_nodes_raw = [n for n in nodes if n.country == "China" and n.type in allowed_types]
    kenya_nodes_raw = [n for n in nodes if n.country == "Kenya" and n.type in allowed_types]

    china_nodes = [{"id": n.id, "name": n.name, "city": n.city, "type": n.type} for n in china_nodes_raw]
    kenya_nodes = [{"id": n.id, "name": n.name, "city": n.city, "type": n.type} for n in kenya_nodes_raw]

    direction_key = request.args.get("direction", "china-kenya")
    origin_id = request.args.get("origin", "").strip()
    destination_id = request.args.get("destination", "").strip()
    weight = request.args.get("weight", "")
    preference_key = _normalize_objective_key(request.args.get("preference", "practical_route"))

    direction_label = DIRECTION_LABELS.get(direction_key, "China → Kenya")
    preference_label = PREFERENCE_LABELS.get(preference_key, "Practical option")

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
    preference_key = _normalize_objective_key(request.args.get("preference", "practical_route"))

    origin_id = request.args.get("origin", "").strip()
    destination_id = request.args.get("destination", "").strip()
    weight = request.args.get("weight", "").strip()
    length_cm_raw = request.args.get("length_cm", "").strip()
    width_cm_raw = request.args.get("width_cm", "").strip()
    height_cm_raw = request.args.get("height_cm", "").strip()

    direction_label = DIRECTION_LABELS.get(direction_key, "China → Kenya")
    preference_label = PREFERENCE_LABELS.get(preference_key, "Practical option")

    nodes = load_nodes()
    node_map = {n.id: n for n in nodes}
    origin_name = node_map.get(origin_id).name if origin_id in node_map else origin_id
    destination_name = node_map.get(destination_id).name if destination_id in node_map else destination_id

    try:
        weight_kg = float(weight) if weight else 500.0
    except (ValueError, TypeError):
        weight_kg = 500.0
    weight_kg = max(0.1, weight_kg)

    def _parse_dim(value: str) -> float | None:
        if not value:
            return None
        try:
            num = float(value)
        except (ValueError, TypeError):
            return None
        if num <= 0:
            return None
        return num

    length_cm = _parse_dim(length_cm_raw)
    width_cm = _parse_dim(width_cm_raw)
    height_cm = _parse_dim(height_cm_raw)

    dims_ok = bool(length_cm and width_cm and height_cm)
    volumetric_weight_kg = None
    if dims_ok:
        volumetric_weight_kg = (float(length_cm) * float(width_cm) * float(height_cm)) / 6000.0

    def _invalid_pair(origin_type: str | None, dest_type: str | None) -> bool:
        if not origin_type or not dest_type:
            return False
        return (origin_type == "airport" and dest_type == "port") or (origin_type == "port" and dest_type == "airport")

    origin_type = node_map.get(origin_id).type if origin_id in node_map else None
    destination_type = node_map.get(destination_id).type if destination_id in node_map else None
    invalid_route_pair = _invalid_pair(origin_type, destination_type)

    engine = RouteEngine()
    route = None
    alternatives = {}
    enriched_alts = {}
    route_insight = ""
    route_story = ""
    decision = {}
    sensitivity = {}

    if not origin_id or not destination_id:
        route = {"success": False, "error": "Please select an origin and destination to generate a route analysis."}
    elif invalid_route_pair:
        route = {
            "success": False,
            "error": "Selected origin and destination types do not form a valid shipment pair.",
        }
    else:
        route = engine.compute_route(
            origin_id,
            destination_id,
            preference_key,
            weight_kg,
            length_cm=length_cm,
            width_cm=width_cm,
            height_cm=height_cm,
        )
        for obj_key in OBJECTIVE_KEYS:
            alternatives[obj_key] = engine.compute_route(
                origin_id,
                destination_id,
                obj_key,
                weight_kg,
                length_cm=length_cm,
                width_cm=width_cm,
                height_cm=height_cm,
            )

        if route.get("success"):
            shipment = route.get("shipment") if isinstance(route.get("shipment"), dict) else {}
            chargeable = float(shipment.get("chargeable_weight_kg") or 0.0)
            actual = float(shipment.get("actual_weight_kg") or 0.0)
            route["shipment_volume_based"] = bool(dims_ok and chargeable > actual + 0.01)

            # Mode-aware pricing basis for results UI.
            mode_keys = {leg.get("mode_key") for leg in (route.get("legs") or []) if isinstance(leg, dict)}
            lines: list[str] = []
            if "air" in mode_keys:
                # Air: explicitly show chargeable weight logic (actual vs volumetric).
                if dims_ok and volumetric_weight_kg is not None:
                    lines.append(
                        f"Air pricing basis: chargeable weight = max(actual {actual:.2f} kg, volumetric {volumetric_weight_kg:.2f} kg) = {chargeable:.2f} kg."
                    )
                else:
                    lines.append(f"Air pricing basis: chargeable weight = actual weight ({actual:.2f} kg).")

            if "sea" in mode_keys:
                # Sea (LCL): explain W/M billing (weight or measure), without air-style chargeable-weight language.
                if dims_ok:
                    volume_cbm = (float(length_cm) * float(width_cm) * float(height_cm)) / 1_000_000.0
                    weight_ton = actual / 1000.0
                    wm = max(volume_cbm, weight_ton)
                    lines.append(
                        f"Sea (LCL) pricing basis: W/M (weight or measure) = max({weight_ton:.3f} t, {volume_cbm:.3f} m³) = {wm:.3f} W/M."
                    )
                else:
                    lines.append("Sea (LCL) pricing basis: typically billed by W/M (weight or volume), using whichever is higher.")

            if "road" in mode_keys or "rail" in mode_keys:
                lines.append("Ground (road/rail) pricing basis: actual shipment weight.")

            route["pricing_basis_lines"] = lines

            if weight_kg < 100:
                route["mode_recommendation"] = "Air recommended for speed"
            elif weight_kg > 300:
                route["mode_recommendation"] = "Sea recommended for cost"
            else:
                route["mode_recommendation"] = ""

            route["route_rationale"] = build_rationale(route, preference_key, alternatives)
            route_insight = build_route_insight(route, preference_key)
            route_story = build_route_story(route)
            enriched_alts = enrich_alternatives(route, preference_key, alternatives)
            decision = build_decision_context(route, preference_key, alternatives)
            sensitivity = build_sensitivity_context(
                origin_id, destination_id, preference_key,
                weight_kg, route, engine,
                length_cm=length_cm,
                width_cm=width_cm,
                height_cm=height_cm,
            )

            # UI: hide practical_route card when it is effectively duplicate.
            try:
                from backend.comparison import routes_nearly_identical
            except Exception:  # pragma: no cover
                routes_nearly_identical = None

            ui_objectives = list(OBJECTIVE_KEYS)
            practical = alternatives.get("practical_route")
            if routes_nearly_identical and practical and preference_key != "practical_route":
                if routes_nearly_identical(practical, alternatives.get("lowest_cost", {})) or routes_nearly_identical(
                    practical, alternatives.get("fastest_delivery", {})
                ):
                    ui_objectives = [k for k in ui_objectives if k != "practical_route"]
                    enriched_alts.pop("practical_route", None)

        else:
            ui_objectives = list(OBJECTIVE_KEYS)

            leg_labels = build_leg_labels(route)
            for i, label in enumerate(leg_labels):
                if i < len(route["legs"]):
                    route["legs"][i]["label"] = label

            # Persist route analysis for logged-in users
            if getattr(g, "user", None):
                path_nodes = route.get("path_nodes", [])
                path_summary = " → ".join([n.get("name", "") for n in path_nodes if n.get("name")])[:1024]
                analysis = RouteAnalysis(
                    user_id=g.user.id,
                    origin=origin_id,
                    destination=destination_id,
                    weight_kg=float(weight_kg),
                    objective=preference_key,
                    total_cost=float(route.get("total_cost", 0.0)),
                    total_time_days=float(route.get("total_time", 0.0)),
                    path_summary=path_summary or f"{origin_id} → {destination_id}",
                )
                db.session.add(analysis)
                db.session.commit()

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
        length_cm=length_cm_raw,
        width_cm=width_cm_raw,
        height_cm=height_cm_raw,
        weight_kg=weight_kg,
        preference=preference_label,
        route=route,
        alternatives=enriched_alts if enriched_alts else alternatives,
        ui_objectives=ui_objectives,
        objective_label=preference_label,
        route_insight=route_insight,
        route_story=route_story,
        decision=decision,
        sensitivity=sensitivity,
    )


@app.route("/hubs")
def hubs():
    nodes = load_nodes()
    return render_template("hubs.html", title="Hubs", nodes=nodes)


@app.route("/about")
def about():
    return render_template("about.html", title="About")


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user = g.user
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        new_pw = (request.form.get("new_password") or "").strip()
        new_pw2 = (request.form.get("new_password_confirm") or "").strip()
        cur_pw = request.form.get("current_password") or ""

        if not username or not email:
            flash("Username and email are required.", "error")
        else:
            taken = (
                User.query.filter(
                    User.id != user.id,
                    or_(User.username == username, User.email == email),
                ).first()
            )
            if taken:
                flash("That username or email is already taken.", "error")
            else:
                want_pw = bool(new_pw or new_pw2)
                if want_pw:
                    if not cur_pw:
                        flash("Enter your current password to set a new password.", "error")
                    elif not user.check_password(cur_pw):
                        flash("Current password is incorrect.", "error")
                    elif len(new_pw) < 6:
                        flash("New password must be at least 6 characters.", "error")
                    elif new_pw != new_pw2:
                        flash("New passwords do not match.", "error")
                    else:
                        user.set_password(new_pw)
                        user.username = username
                        user.email = email
                        db.session.commit()
                        flash("Profile updated.", "success")
                        return redirect(url_for("profile"))
                else:
                    user.username = username
                    user.email = email
                    db.session.commit()
                    flash("Profile updated.", "success")
                    return redirect(url_for("profile"))

    analyses = (
        RouteAnalysis.query.filter_by(user_id=user.id)
        .order_by(RouteAnalysis.created_at.desc())
        .limit(4)
        .all()
    )
    return render_template("profile.html", title="Profile", analyses=analyses)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)

