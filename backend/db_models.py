from __future__ import annotations

from datetime import datetime, timezone

from werkzeug.security import check_password_hash, generate_password_hash

from backend.extensions import db


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(32), nullable=False, default="user", index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)

    analyses = db.relationship("RouteAnalysis", back_populates="user", lazy="dynamic")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class RouteAnalysis(db.Model):
    __tablename__ = "route_analyses"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    origin = db.Column(db.String(128), nullable=False)
    destination = db.Column(db.String(128), nullable=False)
    weight_kg = db.Column(db.Float, nullable=False)
    objective = db.Column(db.String(64), nullable=False)

    total_cost = db.Column(db.Float, nullable=False)
    total_time_days = db.Column(db.Float, nullable=False)
    path_summary = db.Column(db.String(1024), nullable=False)

    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow, index=True)

    user = db.relationship("User", back_populates="analyses")


class Shipment(db.Model):
    """Trackable shipment snapshot derived from a computed route (planner output)."""

    __tablename__ = "shipments"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)

    tracking_number = db.Column(db.String(40), unique=True, nullable=False, index=True)

    origin_id = db.Column(db.String(128), nullable=False)
    origin_name = db.Column(db.String(255), nullable=False)
    destination_id = db.Column(db.String(128), nullable=False)
    destination_name = db.Column(db.String(255), nullable=False)

    direction_key = db.Column(db.String(32), nullable=True)

    objective_key = db.Column(db.String(64), nullable=False, index=True)
    objective_label = db.Column(db.String(128), nullable=False)

    weight_kg = db.Column(db.Float, nullable=False)

    total_estimated_cost = db.Column(db.Float, nullable=False)
    estimated_delivery_days = db.Column(db.Float, nullable=False)

    route_legs = db.Column(db.JSON, nullable=False)
    path_nodes = db.Column(db.JSON, nullable=False)

    path_summary = db.Column(db.String(1024), nullable=False, default="")

    current_status = db.Column(db.String(64), nullable=False, index=True)
    current_stage_index = db.Column(db.Integer, nullable=False, default=0)

    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)
    estimated_arrival = db.Column(db.DateTime, nullable=True)

    user = db.relationship("User", backref=db.backref("shipments", lazy="dynamic"))

