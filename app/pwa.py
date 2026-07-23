"""Public, session-neutral resources required by the installable web app."""

from flask import Blueprint, current_app, make_response, send_from_directory


pwa_bp = Blueprint("pwa", __name__)


@pwa_bp.get("/manifest.webmanifest")
def manifest():
    return send_from_directory(
        current_app.static_folder,
        "manifest.webmanifest",
        mimetype="application/manifest+json",
        conditional=True,
    )


@pwa_bp.get("/service-worker.js")
def service_worker():
    return send_from_directory(
        current_app.static_folder,
        "service-worker.js",
        mimetype="text/javascript",
        conditional=True,
    )


@pwa_bp.get("/offline")
def offline():
    # Render directly through Jinja so Flask context processors do not create or
    # embed a session CSRF token in the document stored by the service worker.
    document = current_app.jinja_env.get_template("offline.html").render()
    response = make_response(document)
    response.mimetype = "text/html"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response
