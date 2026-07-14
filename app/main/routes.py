import json
from datetime import datetime

from flask import Blueprint, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app import seed_database
from app.extensions import db
from app.models import BillRecord, ComplaintTicket, DiagnosticResult, RoamingPackage, User
from app.services.mock_bill_analysis import analyse_bill
from app.services.mock_complaints import classify_complaint
from app.services.mock_diagnostics import result_for_state
from app.services.mock_roaming import recommend_package


main_bp = Blueprint("main", __name__)


@main_bp.get("/")
def index():
    return redirect(url_for("main.app_shell") if current_user.is_authenticated else url_for("auth.login"))


@main_bp.get("/app")
@login_required
def app_shell():
    latest_bill = BillRecord.query.filter_by(user_id=current_user.id).order_by(BillRecord.created_at.desc()).first()
    tickets = ComplaintTicket.query.filter_by(user_id=current_user.id).order_by(ComplaintTicket.created_at.desc()).all()
    diagnostics = DiagnosticResult.query.filter_by(user_id=current_user.id).order_by(DiagnosticResult.created_at.desc()).all()
    return render_template(
        "app/shell.html",
        latest_bill=latest_bill,
        tickets=tickets,
        diagnostics=diagnostics,
        destinations=json.loads(RoamingPackage.query.first().supported_destinations) if RoamingPackage.query.first() else [],
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
    seed_database()
    return jsonify({"ok": True, "message": "Demonstration data has been restored."})

