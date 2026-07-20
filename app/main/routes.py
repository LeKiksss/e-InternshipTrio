import json
import hashlib
from datetime import date, datetime

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required

from app import COUNTRY_FLAGS, seed_database
from app.extensions import db
from app.models import BillRecord, ComplaintTicket, DiagnosticResult, RoamingPackage, User
from app.services.mock_bill_analysis import analyse_bill
from app.services.mock_complaints import classify_complaint
from app.services.mock_diagnostics import result_for_state
from app.services.mock_roaming import (
    adjusted_package,
    calculate_trip_days,
    current_usage_package,
    parse_adjustment,
    recommend_package,
    scale_usage,
)


main_bp = Blueprint("main", __name__)
WORKFLOW_NAMES = {"network", "bill", "complaints", "roaming"}


@main_bp.get("/")
def index():
    return redirect(url_for("main.app_shell") if current_user.is_authenticated else url_for("auth.login"))


@main_bp.get("/app")
@login_required
def app_shell():
    latest_bill = BillRecord.query.filter_by(user_id=current_user.id).order_by(BillRecord.created_at.desc()).first()
    tickets = ComplaintTicket.query.filter_by(user_id=current_user.id).order_by(ComplaintTicket.created_at.desc()).all()
    diagnostics = DiagnosticResult.query.filter_by(user_id=current_user.id).order_by(DiagnosticResult.created_at.desc()).all()
    first_package = RoamingPackage.query.first()
    destinations = sorted(json.loads(first_package.supported_destinations)) if first_package else []
    destination_groups = [
        (letter, [country for country in destinations if country.startswith(letter)])
        for letter in sorted({country[0] for country in destinations})
    ]
    return render_template(
        "app/shell.html",
        latest_bill=latest_bill,
        tickets=tickets,
        diagnostics=diagnostics,
        destinations=destinations,
        destination_groups=destination_groups,
        country_flags=COUNTRY_FLAGS,
    )


@main_bp.get("/api/bootstrap")
@login_required
def bootstrap():
    return jsonify({
        "user": {"id": current_user.id, "full_name": current_user.full_name, "email": current_user.email, "phone_number": current_user.phone_number},
        "diagnostics": [x.to_dict() for x in DiagnosticResult.query.filter_by(user_id=current_user.id).order_by(DiagnosticResult.created_at.desc()).all()],
        "bills": [x.to_dict() for x in BillRecord.query.filter_by(user_id=current_user.id).order_by(BillRecord.created_at.desc()).all()],
        "tickets": [x.to_dict() for x in ComplaintTicket.query.filter_by(user_id=current_user.id).order_by(ComplaintTicket.created_at.desc()).all()],
    })


@main_bp.route("/api/workflows/<name>", methods=["GET", "PUT", "DELETE"])
@login_required
def workflow_state(name):
    if name not in WORKFLOW_NAMES:
        return jsonify({"ok": False, "message": "Unknown workflow."}), 404
    drafts = session.get("workflow_drafts", {})
    if request.method == "GET":
        value = drafts.get(name, {})
        return jsonify({"ok": True, "state": value.get("state", {}), "view": value.get("view", "landing")})
    if request.method == "DELETE":
        drafts.pop(name, None)
        session["workflow_drafts"] = drafts
        session.modified = True
        return jsonify({"ok": True})
    payload = request.get_json(silent=True) or {}
    state = payload.get("state") if isinstance(payload.get("state"), dict) else {}
    view = str(payload.get("view") or "landing")[:40]
    if len(json.dumps(state)) > 3000:
        return jsonify({"ok": False, "message": "The workflow draft is too large to save in this session."}), 400
    drafts[name] = {"state": state, "view": view, "updated_at": datetime.now().isoformat(timespec="seconds")}
    session["workflow_drafts"] = drafts
    session.modified = True
    return jsonify({"ok": True})


@main_bp.post("/api/diagnostics")
@login_required
def save_diagnostic():
    payload = request.get_json(silent=True) or {}
    state = payload.get("state", "strong")
    if state == "failure":
        return jsonify({"ok": False, "message": "The simulated test could not complete. Your existing results are safe."}), 503
    result = result_for_state("weak" if state == "weak" else "strong")
    row = DiagnosticResult(user_id=current_user.id, location_label=payload.get("location") or "Location not saved", **result)
    db.session.add(row)
    db.session.commit()
    return jsonify({"ok": True, "result": row.to_dict()}), 201


@main_bp.delete("/api/diagnostics/<int:result_id>")
@login_required
def delete_diagnostic(result_id):
    row = DiagnosticResult.query.filter_by(id=result_id, user_id=current_user.id).first_or_404()
    db.session.delete(row)
    db.session.commit()
    return jsonify({"ok": True})


@main_bp.post("/api/bills")
@login_required
def save_bill():
    payload = request.get_json(silent=True) or {}
    try:
        values = {key: float(payload.get(key, 0)) for key in ("total_amount", "data_charges", "call_charges", "roaming_charges", "addon_charges")}
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "Enter valid numeric bill amounts."}), 400
    if values["total_amount"] <= 0 or not payload.get("due_date"):
        return jsonify({"ok": False, "message": "Total amount and due date are required."}), 400
    analysis = analyse_bill(values)
    row = BillRecord(user_id=current_user.id, due_date=str(payload["due_date"]), anomaly_summary=analysis["summary"], **values)
    db.session.add(row)
    db.session.commit()
    return jsonify({"ok": True, "bill": row.to_dict(), "analysis": analysis}), 201


@main_bp.post("/api/complaints")
@login_required
def create_complaint():
    payload = request.get_json(silent=True) or {}
    summary = (payload.get("summary") or "").strip()
    if len(summary) < 10:
        return jsonify({"ok": False, "message": "Please add a little more detail before submitting."}), 400
    if payload.get("simulate_failure"):
        return jsonify({"ok": False, "message": "Submission is unavailable in this demo state. Your details remain on screen."}), 503
    diagnosis = classify_complaint(summary, payload.get("category"))
    sequence = ComplaintTicket.query.count() + 142
    row = ComplaintTicket(
        user_id=current_user.id,
        ticket_number=f"ET-{datetime.now().year}-{sequence:05d}",
        category=diagnosis["category"],
        severity=payload.get("severity") or diagnosis["priority"],
        summary=summary,
        status="Submitted",
        latest_update="Your complaint has been received and queued for review.",
        expected_resolution="Within 24 hours" if diagnosis["priority"] == "High" else "Within 2 business days",
        assigned_department=diagnosis["department"],
        location_label=payload.get("location") or "Not provided",
    )
    db.session.add(row)
    db.session.commit()
    return jsonify({"ok": True, "ticket": row.to_dict(), "diagnosis": diagnosis}), 201


@main_bp.get("/api/complaints/<int:ticket_id>")
@login_required
def complaint_detail(ticket_id):
    row = ComplaintTicket.query.filter_by(id=ticket_id, user_id=current_user.id).first_or_404()
    return jsonify({"ok": True, "ticket": row.to_dict()})


@main_bp.post("/api/complaints/<int:ticket_id>/note")
@login_required
def complaint_note(ticket_id):
    row = ComplaintTicket.query.filter_by(id=ticket_id, user_id=current_user.id).first_or_404()
    note = ((request.get_json(silent=True) or {}).get("note") or "").strip()
    if not note:
        return jsonify({"ok": False, "message": "Enter a note first."}), 400
    notes = json.loads(row.notes or "[]")
    notes.append({"text": note, "date": datetime.now().strftime("%d %b, %H:%M")})
    row.notes = json.dumps(notes)
    row.latest_update = "You added supporting information to this ticket."
    db.session.commit()
    return jsonify({"ok": True, "ticket": row.to_dict()})


@main_bp.post("/api/complaints/<int:ticket_id>/close")
@login_required
def close_complaint(ticket_id):
    row = ComplaintTicket.query.filter_by(id=ticket_id, user_id=current_user.id).first_or_404()
    row.status = "Resolved"
    row.latest_update = "Ticket closed by the customer in the prototype."
    db.session.commit()
    return jsonify({"ok": True, "ticket": row.to_dict()})


@main_bp.post("/api/roaming/recommend")
@login_required
def roaming_recommend():
    payload = request.get_json(silent=True) or {}
    destination = payload.get("destination")
    if not destination:
        return jsonify({"ok": False, "message": "Choose a destination first."}), 400
    if payload.get("simulate") == "database":
        return jsonify({"ok": False, "message": "The fictional package catalogue is temporarily unavailable."}), 503
    package = recommend_package(
        RoamingPackage.query.filter_by(active=True).all(), destination,
        int(payload.get("duration") or 1), payload.get("requirements") or "",
        payload.get("rejected_ids") or [],
    )
    if not package:
        return jsonify({"ok": False, "message": "No additional fictional package matches this trip."}), 404
    result = package.to_dict()
    result["destination"] = destination
    result["why"] = package.notes
    return jsonify({"ok": True, "package": result})


@main_bp.post("/api/roaming/current-usage")
@login_required
def roaming_current_usage():
    payload = request.get_json(silent=True) or {}
    destination = (payload.get("destination") or "").strip()
    if not destination:
        return jsonify({"ok": False, "message": "Choose a destination first."}), 400
    try:
        trip_days = calculate_trip_days(payload.get("start_date"), payload.get("end_date"), today=date.today())
    except ValueError as error:
        return jsonify({"ok": False, "message": str(error)}), 400
    return jsonify({
        "ok": True,
        "trip_days": trip_days,
        "usage": scale_usage(trip_days),
        "package": current_usage_package(destination, trip_days),
    })


@main_bp.post("/api/roaming/adjust")
@login_required
def roaming_adjust():
    payload = request.get_json(silent=True) or {}
    destination = (payload.get("destination") or "").strip()
    try:
        trip_days = int(payload.get("trip_days") or 0)
    except (TypeError, ValueError):
        trip_days = 0
    if not destination or trip_days < 1:
        return jsonify({"ok": False, "message": "Complete the destination and travel dates first."}), 400
    text = (payload.get("message") or "").strip()
    if not text:
        return jsonify({"ok": False, "message": "Enter an adjustment first."}), 400
    intent = parse_adjustment(text)
    if not intent:
        return jsonify({
            "ok": False,
            "message": "I could not identify the adjustment. Try asking for more data, more calls, a cheaper option, or longer validity.",
        }), 422
    package = adjusted_package(intent, destination, trip_days)
    return jsonify({"ok": True, "intent": intent, "package": package})


@main_bp.get("/api/roaming/saved")
@login_required
def saved_roaming_recommendations():
    saved = session.get("saved_roaming_recommendations", [])
    if not isinstance(saved, list):
        saved = []
        session["saved_roaming_recommendations"] = saved
        session.modified = True
    return jsonify({"ok": True, "recommendations": saved})


@main_bp.post("/api/roaming/saved")
@login_required
def save_roaming_recommendation():
    payload = request.get_json(silent=True) or {}
    required = ("package_id", "package_name", "destination", "start_date", "end_date", "trip_days")
    if any(not payload.get(field) for field in required):
        return jsonify({"ok": False, "message": "The recommendation is incomplete and could not be saved."}), 400
    allowed = (
        "package_id", "package_name", "recommendation_name", "destination", "start_date", "end_date", "trip_days",
        "price", "currency", "validity_days", "data_allowance", "local_minutes",
        "international_minutes", "sms_allowance", "preferred_network", "activation_code",
        "activation_instructions", "explanation",
    )
    recommendation = {field: payload.get(field) for field in allowed}
    identity = "|".join(str(recommendation.get(field) or "") for field in ("package_id", "destination", "start_date", "end_date"))
    recommendation["saved_id"] = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    recommendation["saved_at"] = datetime.now().isoformat(timespec="seconds")
    saved = session.get("saved_roaming_recommendations", [])
    if not isinstance(saved, list):
        saved = []
    existing = next((item for item in saved if item.get("saved_id") == recommendation["saved_id"]), None)
    if existing:
        return jsonify({"ok": True, "duplicate": True, "recommendation": existing, "recommendations": saved})
    saved.append(recommendation)
    session["saved_roaming_recommendations"] = saved[-4:]
    session.modified = True
    return jsonify({"ok": True, "duplicate": False, "recommendation": recommendation, "recommendations": session["saved_roaming_recommendations"]}), 201


@main_bp.delete("/api/roaming/saved/<saved_id>")
@login_required
def remove_roaming_recommendation(saved_id):
    saved = session.get("saved_roaming_recommendations", [])
    if not isinstance(saved, list):
        saved = []
    updated = [item for item in saved if item.get("saved_id") != saved_id]
    if len(updated) == len(saved):
        return jsonify({"ok": False, "message": "Saved recommendation not found."}), 404
    session["saved_roaming_recommendations"] = updated
    session.modified = True
    return jsonify({"ok": True, "recommendations": updated})


@main_bp.post("/api/profile")
@login_required
def update_profile():
    payload = request.get_json(silent=True) or {}
    name = (payload.get("full_name") or "").strip()
    phone = (payload.get("phone_number") or "").replace(" ", "")
    if len(name) < 2 or len(phone) < 9:
        return jsonify({"ok": False, "message": "Enter a valid name and UAE mobile number."}), 400
    duplicate = User.query.filter(User.phone_number == phone, User.id != current_user.id).first()
    if duplicate:
        return jsonify({"ok": False, "message": "That phone number belongs to another prototype account."}), 400
    current_user.full_name = name
    current_user.phone_number = phone
    current_user.notification_preferences = payload.get("notification_preferences") or current_user.notification_preferences
    current_user.preferred_contact_method = payload.get("preferred_contact_method") or current_user.preferred_contact_method
    db.session.commit()
    return jsonify({"ok": True, "message": "Profile preferences saved."})


@main_bp.post("/api/demo/reset")
@login_required
def reset_demo():
    if current_user.email != "demo@prototype.local":
        return jsonify({"ok": False, "message": "Reset is available for the seeded demonstration account only."}), 400
    DiagnosticResult.query.filter_by(user_id=current_user.id).delete()
    BillRecord.query.filter_by(user_id=current_user.id).delete()
    ComplaintTicket.query.filter_by(user_id=current_user.id).delete()
    db.session.commit()
    session.pop("workflow_drafts", None)
    session.pop("saved_roaming_recommendations", None)
    session.modified = True
    seed_database()
    return jsonify({"ok": True, "message": "Demonstration data has been restored."})
