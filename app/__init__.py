import json
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, jsonify, redirect, url_for
from flask_wtf.csrf import CSRFError, generate_csrf

from config import Config
from .extensions import csrf, db, login_manager
from .models import BillRecord, ComplaintTicket, DiagnosticResult, RoamingPackage, User


COUNTRY_FLAGS = {
    "Australia": "🇦🇺",
    "Austria": "🇦🇹",
    "Bahrain": "🇧🇭",
    "Belgium": "🇧🇪",
    "Brazil": "🇧🇷",
    "Canada": "🇨🇦",
    "China": "🇨🇳",
    "Egypt": "🇪🇬",
    "France": "🇫🇷",
    "Germany": "🇩🇪",
    "Greece": "🇬🇷",
    "India": "🇮🇳",
    "Indonesia": "🇮🇩",
    "Ireland": "🇮🇪",
    "Italy": "🇮🇹",
    "Japan": "🇯🇵",
    "Malaysia": "🇲🇾",
    "Maldives": "🇲🇻",
    "Morocco": "🇲🇦",
    "Netherlands": "🇳🇱",
    "New Zealand": "🇳🇿",
    "Oman": "🇴🇲",
    "Philippines": "🇵🇭",
    "Saudi Arabia": "🇸🇦",
    "Singapore": "🇸🇬",
    "South Africa": "🇿🇦",
    "South Korea": "🇰🇷",
    "Spain": "🇪🇸",
    "Switzerland": "🇨🇭",
    "Turkey": "🇹🇷",
    "United Kingdom": "🇬🇧",
    "United States": "🇺🇸",
}
DESTINATIONS = sorted(COUNTRY_FLAGS)


def seed_database():
    demo = User.query.filter_by(email="demo@prototype.local").first()
    if not demo:
        demo = User(
            full_name="Prototype Demo User",
            email="demo@prototype.local",
            phone_number="+971501234567",
            notification_preferences="Important updates",
            preferred_contact_method="SMS",
        )
        demo.set_password("Demo123!")
        db.session.add(demo)
        db.session.flush()
    package_data = [
        ("Travel Data Lite", 95, 7, "5 GB", 30, 25, "*170*101#", "Demo Network A", "Best for navigation, messaging, and light browsing."),
        ("Travel Connect", 175, 7, "12 GB", 120, 50, "*170*102#", "Preferred Partner 1", "Balanced data and calling for a one-week trip."),
        ("Global Explorer", 320, 14, "30 GB", 300, 100, "*170*103#", "Demo Network B", "Extended validity for longer multi-purpose trips."),
        ("Voice Traveller", 210, 10, "8 GB", 500, 50, "*170*104#", "Demo Network A", "Designed for frequent daily calls with moderate data."),
        ("Data Max Abroad", 275, 10, "40 GB", 60, 50, "*170*105#", "Preferred Partner 1", "High data allowance for streaming and heavy use."),
    ]
    supported_destinations = json.dumps(DESTINATIONS)
    for name, price, days, data, voice, sms, code, network, notes in package_data:
        package = RoamingPackage.query.filter_by(name=name).first()
        if package:
            package.supported_destinations = supported_destinations
        else:
            db.session.add(RoamingPackage(
                name=name,
                supported_destinations=supported_destinations,
                price=price,
                currency="AED",
                validity_days=days,
                data_allowance=data,
                voice_minutes=voice,
                sms_allowance=sms,
                activation_code=code,
                activation_instructions="Dial the fictional code, review the confirmation screen, then confirm. No real activation occurs in this prototype.",
                preferred_network=network,
                notes=notes,
            ))

    if demo.id and not DiagnosticResult.query.filter_by(user_id=demo.id).first():
        db.session.add(DiagnosticResult(
            user_id=demo.id, download_speed=172.4, upload_speed=29.8, latency=21,
            verdict="Excellent", location_label="Downtown Dubai — demo location",
            created_at=datetime.now() - timedelta(days=5),
        ))
    if demo.id and not BillRecord.query.filter_by(user_id=demo.id).first():
        db.session.add(BillRecord(
            user_id=demo.id, total_amount=468, due_date=(datetime.now() + timedelta(days=5)).strftime("%d %b %Y"),
            data_charges=240, call_charges=72, roaming_charges=96, addon_charges=60,
            anomaly_summary="Bill is 28% higher than usual; roaming charges caused most of the increase.",
        ))
    if demo.id and not ComplaintTicket.query.filter_by(user_id=demo.id).first():
        db.session.add(ComplaintTicket(
            user_id=demo.id, ticket_number="ET-2026-00142", category="Network", severity="High",
            summary="Intermittent mobile data near the Marina during afternoon hours.", status="Assigned",
            latest_update="Assigned to Network Operations for an area coverage review.",
            expected_resolution="Within 24 hours", assigned_department="Network Operations",
            location_label="Dubai Marina — demo location",
        ))
    db.session.commit()


def create_app(config_object=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please sign in to continue."
    login_manager.login_message_category = "info"

    from .auth.routes import auth_bp
    from .main.routes import main_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    @app.context_processor
    def inject_csrf():
        return {"csrf_token_value": generate_csrf()}

    @app.errorhandler(CSRFError)
    def handle_csrf(error):
        if app.testing:
            raise error
        return jsonify({"ok": False, "message": "Your session expired. Refresh and try again."}), 400

    @app.errorhandler(404)
    def not_found(_error):
        return redirect(url_for("main.index"))

    with app.app_context():
        db.create_all()
        seed_database()

    return app
