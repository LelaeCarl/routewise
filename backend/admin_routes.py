from __future__ import annotations

from flask import Blueprint, render_template

from backend.auth_utils import admin_required
from backend.data_loader import load_edges, load_nodes
from backend.db_models import RouteAnalysis, User


admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.route("/")
@admin_required
def dashboard():
    nodes = load_nodes()
    edges = load_edges()

    total_users = User.query.count()
    total_analyses = RouteAnalysis.query.count()

    recent_users = User.query.order_by(User.created_at.desc()).limit(5).all()
    recent_analyses = RouteAnalysis.query.order_by(RouteAnalysis.created_at.desc()).limit(5).all()

    return render_template(
        "admin/dashboard.html",
        title="Admin",
        total_users=total_users,
        total_analyses=total_analyses,
        total_nodes=len(nodes),
        total_edges=len(edges),
        recent_users=recent_users,
        recent_analyses=recent_analyses,
    )


@admin_bp.route("/users")
@admin_required
def users():
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template("admin/users.html", title="Manage users", users=users)


@admin_bp.route("/analyses")
@admin_required
def analyses():
    analyses = RouteAnalysis.query.order_by(RouteAnalysis.created_at.desc()).all()
    return render_template("admin/analyses.html", title="Route analyses", analyses=analyses)


@admin_bp.route("/network/nodes")
@admin_required
def network_nodes():
    nodes = load_nodes()
    return render_template("admin/nodes.html", title="Inspect nodes", nodes=nodes)


@admin_bp.route("/network/edges")
@admin_required
def network_edges():
    edges = load_edges()
    return render_template("admin/edges.html", title="Inspect edges", edges=edges)


@admin_bp.route("/pricing")
@admin_required
def pricing():
    # Pricing is currently implicit in the route engine's weight-based cost model.
    return render_template("admin/pricing.html", title="Inspect pricing")

