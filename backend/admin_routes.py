from __future__ import annotations

from flask import Blueprint, flash, g, redirect, render_template, request, url_for
from sqlalchemy import or_

from backend.auth_utils import admin_required
from backend.data_loader import load_edges, load_nodes
from backend.db_models import RouteAnalysis, User
from backend.extensions import db


admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def _clean(s: str | None) -> str:
    return (s or "").strip()


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


@admin_bp.route("/users/add", methods=["POST"])
@admin_required
def users_add():
    username = _clean(request.form.get("username"))
    email = _clean(request.form.get("email")).lower()
    password = request.form.get("password") or ""
    role = _clean(request.form.get("role", "user"))
    if role not in ("user", "admin"):
        role = "user"

    if not username or not email or not password:
        flash("Username, email, and password are required.", "error")
        return redirect(url_for("admin.users"))
    if len(password) < 6:
        flash("Password must be at least 6 characters.", "error")
        return redirect(url_for("admin.users"))

    if User.query.filter(or_(User.username == username, User.email == email)).first():
        flash("An account with that username or email already exists.", "error")
        return redirect(url_for("admin.users"))

    user = User(username=username, email=email, role=role)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    flash(f"Created user “{username}”.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def users_delete(user_id: int):
    target = User.query.get_or_404(user_id)
    if target.id == g.user.id:
        flash("You cannot delete your own account from here.", "error")
        return redirect(url_for("admin.users"))

    if target.is_admin and User.query.filter_by(role="admin").count() <= 1:
        flash("Cannot delete the last admin account.", "error")
        return redirect(url_for("admin.users"))

    RouteAnalysis.query.filter_by(user_id=target.id).delete(synchronize_session=False)
    db.session.delete(target)
    db.session.commit()
    flash("User deleted.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@admin_required
def user_edit(user_id: int):
    member = User.query.get_or_404(user_id)

    if request.method == "POST":
        username = _clean(request.form.get("username"))
        email = _clean(request.form.get("email")).lower()
        role = _clean(request.form.get("role", "user"))
        new_password = request.form.get("password") or ""

        if role not in ("user", "admin"):
            role = "user"

        if not username or not email:
            flash("Username and email are required.", "error")
            return (
                render_template(
                    "admin/user_edit.html",
                    title=f"Edit {member.username}",
                    member=member,
                    form=request.form,
                ),
                400,
            )

        if member.is_admin and role == "user" and User.query.filter_by(role="admin").count() <= 1:
            flash("Cannot demote the last admin.", "error")
            return (
                render_template(
                    "admin/user_edit.html",
                    title=f"Edit {member.username}",
                    member=member,
                    form=request.form,
                ),
                400,
            )

        taken = (
            User.query.filter(
                User.id != member.id,
                or_(User.username == username, User.email == email),
            ).first()
        )
        if taken:
            flash("That username or email is already in use.", "error")
            return (
                render_template(
                    "admin/user_edit.html",
                    title=f"Edit {member.username}",
                    member=member,
                    form=request.form,
                ),
                400,
            )

        if new_password:
            if len(new_password) < 6:
                flash("New password must be at least 6 characters.", "error")
                return (
                    render_template(
                        "admin/user_edit.html",
                        title=f"Edit {member.username}",
                        member=member,
                        form=request.form,
                    ),
                    400,
                )
            member.set_password(new_password)

        member.username = username
        member.email = email
        member.role = role
        db.session.commit()
        flash("Account updated.", "success")
        return redirect(url_for("admin.users"))

    return render_template(
        "admin/user_edit.html",
        title=f"Edit {member.username}",
        member=member,
        form=None,
    )


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

