import json
from datetime import datetime, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from flask_login import UserMixin

from .extensions import db


password_hasher = PasswordHasher()


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    phone_number = db.Column(db.String(30), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(512), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    notification_preferences = db.Column(db.String(40), default="Important updates", nullable=False)
    preferred_contact_method = db.Column(db.String(30), default="SMS", nullable=False)

    complaints = db.relationship("ComplaintTicket", backref="user", lazy=True, cascade="all, delete-orphan")
    diagnostics = db.relationship("DiagnosticResult", backref="user", lazy=True, cascade="all, delete-orphan")
    bills = db.relationship("BillRecord", backref="user", lazy=True, cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = password_hasher.hash(password)

    def check_password(self, password):
        try:
            valid = password_hasher.verify(self.password_hash, password)
            if valid and password_hasher.check_needs_rehash(self.password_hash):
                self.password_hash = password_hasher.hash(password)
                db.session.commit()
            return valid
        except (VerifyMismatchError, InvalidHashError):
            return False


class RoamingPackage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    supported_destinations = db.Column(db.Text, nullable=False)
    price = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(8), default="AED", nullable=False)
    validity_days = db.Column(db.Integer, nullable=False)
    data_allowance = db.Column(db.String(30), nullable=False)
    voice_minutes = db.Column(db.Integer, nullable=False)
    sms_allowance = db.Column(db.Integer, nullable=False)
    activation_code = db.Column(db.String(30), nullable=False)
    activation_instructions = db.Column(db.Text, nullable=False)
    preferred_network = db.Column(db.String(100), nullable=False)
    notes = db.Column(db.Text, default="")
    active = db.Column(db.Boolean, default=True, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    @property
    def destinations(self):
        return json.loads(self.supported_destinations)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "destinations": self.destinations,
            "price": self.price,
            "currency": self.currency,
            "validity_days": self.validity_days,
            "data_allowance": self.data_allowance,
            "voice_minutes": self.voice_minutes,
            "sms_allowance": self.sms_allowance,
            "activation_code": self.activation_code,
            "activation_instructions": self.activation_instructions,
            "preferred_network": self.preferred_network,
            "notes": self.notes,
            "updated_at": self.updated_at.strftime("%d %b %Y"),
        }


class ComplaintTicket(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    ticket_number = db.Column(db.String(40), unique=True, nullable=False, index=True)
    category = db.Column(db.String(50), nullable=False)
    severity = db.Column(db.String(30), nullable=False)
    summary = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(30), default="Submitted", nullable=False)
    latest_update = db.Column(db.Text, default="Your complaint was received.", nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    expected_resolution = db.Column(db.String(80), nullable=False)
    assigned_department = db.Column(db.String(100), default="Customer Care", nullable=False)
    location_label = db.Column(db.String(120), default="Not provided")
    notes = db.Column(db.Text, default="[]", nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "ticket_number": self.ticket_number,
            "category": self.category,
            "severity": self.severity,
            "summary": self.summary,
            "status": self.status,
            "latest_update": self.latest_update,
            "created_at": self.created_at.strftime("%d %b %Y, %H:%M"),
            "expected_resolution": self.expected_resolution,
            "assigned_department": self.assigned_department,
            "location_label": self.location_label,
            "notes": json.loads(self.notes or "[]"),
        }


class DiagnosticResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    download_speed = db.Column(db.Float, nullable=False)
    upload_speed = db.Column(db.Float, nullable=False)
    latency = db.Column(db.Float, nullable=False)
    verdict = db.Column(db.String(255), nullable=False)
    location_label = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "download_speed": self.download_speed,
            "upload_speed": self.upload_speed,
            "latency": self.latency,
            "verdict": self.verdict,
            "location_label": self.location_label,
            "created_at": self.created_at.strftime("%d %b %Y, %H:%M"),
        }


class BillRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    total_amount = db.Column(db.Float, nullable=False)
    due_date = db.Column(db.String(30), nullable=False)
    data_charges = db.Column(db.Float, default=0, nullable=False)
    call_charges = db.Column(db.Float, default=0, nullable=False)
    roaming_charges = db.Column(db.Float, default=0, nullable=False)
    addon_charges = db.Column(db.Float, default=0, nullable=False)
    anomaly_summary = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "total_amount": self.total_amount,
            "due_date": self.due_date,
            "data_charges": self.data_charges,
            "call_charges": self.call_charges,
            "roaming_charges": self.roaming_charges,
            "addon_charges": self.addon_charges,
            "anomaly_summary": self.anomaly_summary,
            "created_at": self.created_at.strftime("%d %b %Y"),
        }

