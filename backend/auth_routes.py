from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from backend.db_models import User
from backend.extensions import db


auth_bp = Blueprint("auth", __name__)


def _clean(s: str) -> str:
    return (s or "").strip()


def _safe_next_url(nxt: str) -> str | None:
    """Allow only same-origin relative paths (blocks open redirects)."""
    nxt = (nxt or "").strip()
    if not nxt.startswith("/"):
        return None
    if nxt.startswith("//"):
        return None
    if "\n" in nxt or "\r" in nxt or "\\" in nxt:
        return None
    return nxt


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("auth/register.html", title="Create account")

    username = _clean(request.form.get("username", ""))
    email = _clean(request.form.get("email", "")).lower()
    password = request.form.get("password", "") or ""

    if not username or not email or not password:
        flash("Please fill in all fields.", "error")
        return render_template("auth/register.html", title="Create account", form=request.form), 400

    if len(password) < 6:
        flash("Password must be at least 6 characters.", "error")
        return render_template("auth/register.html", title="Create account", form=request.form), 400

    if User.query.filter((User.username == username) | (User.email == email)).first():
        flash("An account with that username or email already exists.", "error")
        return render_template("auth/register.html", title="Create account", form=request.form), 400

    user = User(username=username, email=email, role="user")
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    session["user_id"] = user.id
    flash("Account created. You’re signed in.", "success")

    nxt = _safe_next_url(_clean(request.form.get("next") or request.args.get("next", "")))
    if nxt:
        return redirect(nxt)
    return redirect(url_for("home"))


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("auth/login.html", title="Log in")

    email = _clean(request.form.get("email", "")).lower()
    password = request.form.get("password", "") or ""

    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        flash("Invalid email or password.", "error")
        return render_template("auth/login.html", title="Log in", form=request.form), 401

    session["user_id"] = user.id
    flash("Logged in successfully.", "success")

    nxt = _safe_next_url(_clean(request.form.get("next") or request.args.get("next", "")))
    if nxt:
        return redirect(nxt)
    return redirect(url_for("home"))


@auth_bp.route("/logout")
def logout():
    session.pop("user_id", None)
    flash("You’ve been logged out.", "success")
    return redirect(url_for("auth.login"))

