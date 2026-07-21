import json
import hashlib
from datetime import datetime

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required

from app import COUNTRY_FLAGS, seed_database
from app.extensions import db
from app.models import (
    BillRecord,
    ComplaintTicket,
    DiagnosticResult,
    RoamingPackage,
    User,
    UserMonthlyUsage,
)
from app.services.mock_bill_analysis import analyse_bill
from app.services.mock_complaints import classify_complaint
from app.services.mock_diagnostics import result_for_state
from app.services.roaming_recommendation import build_recommendation


main_bp = Blueprint("main", __name__)
WORKFLOW_NAMES = {"network", "bill", "complaints", "roaming"}


@main_bp.get("/")
def index():
    return redirect(url_for("main.app_shell") if current_user.is_authenticated else url_for("auth.login"))


@main_bp.get("/app")
@login_required
def app_shell():
    latest_bill = BillRecord.query.filter_by(user_id=current_user.id).order_by(BillRecord.created_at.desc()).first()
    usage_history = (
        UserMonthlyUsage.query.filter_by(user_id=current_user.id)
        .order_by(UserMonthlyUsage.usage_month.desc())
        .limit(6)
        .all()
    )
    usage_history.reverse()
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
        usage_history=usage_history,
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
        return jsonify({"ok": False, "message": "The connection test could not complete. Your existing results are safe."}), 503
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
        return jsonify({"ok": False, "message": "Submission is temporarily unavailable. Your details remain on screen."}), 503
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
    row.latest_update = "Ticket closed by the customer."
    db.session.commit()
    return jsonify({"ok": True, "ticket": row.to_dict()})


@main_bp.post("/api/roaming/recommend")
@login_required
def roaming_recommend():
    payload = request.get_json(silent=True) or {}
    destination = (payload.get("destination") or "").strip()
    if destination not in COUNTRY_FLAGS:
        return jsonify({"ok": False, "message": "Choose a destination first."}), 400
    if payload.get("simulate") == "database":
        return jsonify({"ok": False, "message": "The package catalogue is temporarily unavailable."}), 503
    try:
        recommendation = build_recommendation(
            current_user,
            destination,
            payload.get("start_date"),
            payload.get("end_date"),
        )
    except ValueError as error:
        return jsonify({"ok": False, "message": str(error)}), 400
    session["roaming_current_recommendation"] = recommendation
    session["roaming_conversation"] = []
    session.modified = True
    return jsonify({"ok": True, **recommendation})


@main_bp.post("/api/roaming/current-usage")
@login_required
def roaming_current_usage():
    return roaming_recommend()


@main_bp.post("/api/roaming/refine")
@login_required
def roaming_refine():
    payload = request.get_json(silent=True) or {}
    message = (payload.get("message") or "").strip()
    if not message:
        return jsonify({"ok": False, "message": "Enter an adjustment first."}), 400
    current = session.get("roaming_current_recommendation")
    if not isinstance(current, dict) or current.get("recommendation_id") != payload.get("current_recommendation_id"):
        return jsonify({"ok": False, "message": "Start from the current recommendation before changing it."}), 409
    destination = current.get("destination")
    trip = current.get("trip", {})
    conversation = session.get("roaming_conversation", [])
    if not isinstance(conversation, list):
        conversation = []
    try:
        recommendation = build_recommendation(
            current_user,
            destination,
            trip.get("start_date"),
            trip.get("end_date"),
            latest_message=message,
            current_recommendation=current,
            conversation=conversation,
        )
    except ValueError as error:
        return jsonify({"ok": False, "message": str(error)}), 400
    conversation.extend(
        [
            {"role": "user", "message": message[:500]},
            {"role": "assistant", "message": recommendation.get("modification_summary") or recommendation["reason"]},
        ]
    )
    session["roaming_conversation"] = conversation[-12:]
    session["roaming_current_recommendation"] = recommendation
    session.modified = True
    return jsonify({"ok": True, **recommendation})


@main_bp.get("/api/roaming/current")
@login_required
def roaming_current_recommendation():
    recommendation = session.get("roaming_current_recommendation")
    if not isinstance(recommendation, dict):
        return jsonify({"ok": False, "message": "No current recommendation is available."}), 404
    conversation = session.get("roaming_conversation", [])
    return jsonify(
        {
            "ok": True,
            "recommendation": recommendation,
            "conversation": conversation if isinstance(conversation, list) else [],
        }
    )


@main_bp.post("/api/roaming/adjust")
@login_required
def roaming_adjust_compatibility():
    return roaming_refine()


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
    current = session.get("roaming_current_recommendation")
    if not isinstance(current, dict) or current.get("recommendation_id") != payload.get("recommendation_id"):
        return jsonify({"ok": False, "message": "The recommendation is incomplete and could not be saved."}), 400
    recommendation = json.loads(json.dumps(current))
    recommendation["saved_id"] = hashlib.sha256(
        recommendation["recommendation_id"].encode("utf-8")
    ).hexdigest()[:16]
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
        return jsonify({"ok": False, "message": "That phone number belongs to another account."}), 400
    current_user.full_name = name
    current_user.phone_number = phone
    current_user.notification_preferences = payload.get("notification_preferences") or current_user.notification_preferences
    current_user.preferred_contact_method = payload.get("preferred_contact_method") or current_user.preferred_contact_method
    db.session.commit()
    return jsonify({"ok": True, "message": "Profile preferences saved."})


@main_bp.post("/api/demo/reset")
@login_required
def reset_demo():
    if current_user.email in {"demo@prototype.local", "aisha@example.test"}:
        DiagnosticResult.query.filter_by(user_id=current_user.id).delete()
        BillRecord.query.filter_by(user_id=current_user.id).delete()
        ComplaintTicket.query.filter_by(user_id=current_user.id).delete()
        db.session.commit()
    session.pop("workflow_drafts", None)
    session.pop("saved_roaming_recommendations", None)
    session.pop("roaming_current_recommendation", None)
    session.pop("roaming_conversation", None)
    session.modified = True
    seed_database()
    return jsonify({"ok": True, "message": "Account data has been restored."})
