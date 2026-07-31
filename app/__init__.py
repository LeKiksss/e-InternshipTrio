import logging
from pathlib import Path

import click
from flask import Flask, jsonify, redirect, request, url_for
from flask_wtf.csrf import CSRFError, generate_csrf
from werkzeug.middleware.proxy_fix import ProxyFix

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
    if app.config.get("PUBLIC_HTTPS_MODE"):
        app.config.update(
            SESSION_COOKIE_SECURE=True,
            SESSION_COOKIE_HTTPONLY=True,
            SESSION_COOKIE_SAMESITE="Lax",
            REMEMBER_COOKIE_SECURE=True,
            REMEMBER_COOKIE_HTTPONLY=True,
            REMEMBER_COOKIE_SAMESITE="Lax",
            PREFERRED_URL_SCHEME="https",
        )
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=0,
            x_proto=1,
            x_host=1,
            x_port=0,
            x_prefix=0,
        )
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
    from .pwa import pwa_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(pwa_bp)

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
        if request.path.startswith(f"{app.static_url_path}/"):
            return app.response_class("Not found", status=404, mimetype="text/plain")
        return redirect(url_for("main.index"))

    @app.after_request
    def apply_response_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")

        endpoint = request.endpoint or ""
        if endpoint == "pwa.service_worker":
            response.headers["Cache-Control"] = "no-store, max-age=0"
            response.headers["Service-Worker-Allowed"] = "/"
        elif endpoint in {"pwa.manifest", "pwa.offline"} or endpoint == "static":
            response.headers["Cache-Control"] = "no-cache, max-age=0, must-revalidate"
        else:
            response.headers["Cache-Control"] = "no-store, private, max-age=0"
            response.headers["Pragma"] = "no-cache"
        return response

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

    @app.cli.command("smart-history-stats")
    def smart_history_stats_command():
        """Show aggregate, privacy-safe Smart Recommendation History counts."""

        from .services.smart_history import smart_history_stats

        stats = smart_history_stats()
        click.echo(f'Total Smart History entries: {stats["total_entries"]}')
        click.echo(f'Total successful history hits: {stats["total_hits"]}')
        click.echo(f'Split entries: {stats["split_entries"]}')
        click.echo(f'Non-split entries: {stats["non_split_entries"]}')

    @app.cli.command("clear-smart-history")
    @click.option(
        "--confirm",
        is_flag=True,
        help="Confirm deletion of Smart Recommendation History only.",
    )
    def clear_smart_history_command(confirm):
        """Delete only the shared Smart Recommendation History table rows."""

        if not confirm:
            raise click.ClickException(
                "Refusing to clear Smart History without --confirm."
            )
        from .services.smart_history import clear_smart_history

        removed = clear_smart_history()
        click.echo(f"Cleared {removed} Smart History entries.")

    return app
