import logging
from pathlib import Path

import click
from flask import Flask, jsonify, redirect, url_for
from flask_wtf.csrf import CSRFError, generate_csrf

from config import Config
from .extensions import csrf, db, login_manager
from .models import User


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
    from .seed_data import seed_all

    return seed_all()


def create_app(config_object=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object)
    logging.getLogger("app.services").setLevel(logging.INFO)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    request_log_dir = app.config.get("GEMINI_REQUEST_LOG_DIR")
    if request_log_dir:
        Path(request_log_dir).mkdir(parents=True, exist_ok=True)

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
        from .schema_upgrade import upgrade_sqlite_schema

        upgrade_sqlite_schema()
        db.create_all()
        seed_database()

    @app.cli.command("seed-data")
    def seed_data_command():
        """Create or update the required users, usage history, and packages."""

        counts = seed_database()
        click.echo(
            "Seeded "
            f'{counts["seeded_users"]} users, '
            f'{counts["usage_rows"]} usage rows, and '
            f'{counts["active_packages"]} active packages.'
        )

    return app
