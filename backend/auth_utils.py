from __future__ import annotations

from functools import wraps
from typing import Callable, TypeVar

from flask import flash, g, redirect, request, url_for


F = TypeVar("F", bound=Callable[..., object])


def _safe_next_path() -> str:
    # Prefer full_path to preserve query params; Flask includes a trailing "?"
    # when no query string is present.
    nxt = request.full_path or request.path or "/"
    if nxt.endswith("?"):
        nxt = nxt[:-1]
    return nxt


def login_required(fn: F) -> F:
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not getattr(g, "user", None):
            flash("Please log in to continue.", "warning")
            return redirect(url_for("auth.login", next=_safe_next_path()))
        return fn(*args, **kwargs)

    return wrapper  # type: ignore[return-value]


def admin_required(fn: F) -> F:
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = getattr(g, "user", None)
        if not user:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("auth.login", next=_safe_next_path()))
        if not getattr(user, "is_admin", False):
            flash("Admin access required.", "error")
            return redirect(url_for("profile"))
        return fn(*args, **kwargs)

    return wrapper  # type: ignore[return-value]

