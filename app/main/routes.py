import json
import hashlib
import logging
from datetime import datetime

from flask import (
    Blueprint,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
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
from app.services.gemini_recommender import (
    GeminiRateLimited,
    GeminiUnavailable,
)
from app.services.gemini_requirements_interpreter import (
    interpret_requirements_locally,
    request_requirements_interpretation,
    validate_interpreted_requirements,
)
from app.services.recommendation_values import canonical_string
from app.services.roaming_chat_intent import classify_roaming_chat_intent
from app.services.roaming_history import (
    append_recommendation_history,
    clear_recommendation_history,
    get_original_history_entry,
    get_previous_history_entry,
    start_recommendation_history,
)
from app.services.roaming_recommendation import build_recommendation
from app.services.user_requirement_parser import parse_user_requirements


main_bp = Blueprint("main", __name__)
LOGGER = logging.getLogger(__name__)
WORKFLOW_NAMES = {"network", "bill", "complaints", "roaming"}
ROAMING_GEMINI_INTERACTION_KEY = "roaming_gemini_interaction_id"
ROAMING_PLANNER_INITIALIZED_KEY = "roaming_planner_initialized"
ROAMING_PENDING_CLARIFICATION_KEY = "roaming_pending_clarification"


def _append_roaming_conversation(conversation, user_message, assistant_message):
    conversation.extend(
        [
            {"role": "user", "message": user_message[:500]},
            {"role": "assistant", "message": assistant_message[:500]},
        ]
    )
    return conversation[-12:]


def _requirements_state_from_recommendation(recommendation):
    stored = (recommendation or {}).get("_requirements_state")
    if isinstance(stored, dict):
        return stored

    trip = (recommendation or {}).get("trip", {})
    values = (
        (recommendation or {})
        .get("usage_analysis", {})
        .get("requirements", {})
    )
    segments = (recommendation or {}).get("segments") or []
    split_details = [
        {
            "start_day": int(segment["start_day"]),
            "end_day": int(segment["end_day"]),
            **{
                metric: canonical_string(
                    segment.get("requirements", {}).get(metric, 0),
                    field=metric,
                )
                for metric in (
                    "data_gb",
                    "local_minutes",
                    "international_minutes",
                    "sms",
                )
            },
        }
        for segment in segments
    ]
    return {
        **{
            metric: canonical_string(values.get(metric, 0), field=metric)
            for metric in (
                "data_gb",
                "local_minutes",
                "international_minutes",
                "sms",
            )
        },
        "period_days": int(trip.get("trip_days", 0)),
        "split": bool(split_details),
        "split_details": split_details or None,
    }


def _current_plan_allowances(current):
    selection = (current or {}).get("selection") or {}
    fields = {
        "data_gb": "total_data_gb",
        "local_minutes": "total_local_minutes",
        "international_minutes": "total_international_minutes",
        "sms": "total_sms",
    }
    return {
        metric: canonical_string(selection.get(field, 0), field=metric)
        for metric, field in fields.items()
    }


def _roaming_interpreter_context(message, current):
    pending = session.get(ROAMING_PENDING_CLARIFICATION_KEY)
    if not isinstance(pending, dict):
        pending = None
    context = {
        "raw_user_message": message,
        "current_requirements": _requirements_state_from_recommendation(
            current
        ),
        "trip_context": {
            "destination": current.get("destination"),
            **(current.get("trip") or {}),
        },
        "current_plan_allowances": _current_plan_allowances(current),
        "relative_increments": {
            "data_gb": "0.001000",
            "local_minutes": "1.000000",
            "international_minutes": "1.000000",
            "sms": "1.000000",
        },
    }
    if pending:
        context["pending_clarification"] = {
            "original_request": pending.get("original_request"),
            "prior_answers": list(pending.get("prior_answers") or []),
        }
    return context, pending


def _interpret_roaming_refinement(message, current):
    context, pending = _roaming_interpreter_context(message, current)
    decision = request_requirements_interpretation(
        context,
        api_key=current_app.config.get("GEMINI_API_KEY", ""),
        model=current_app.config.get(
            "GEMINI_INTERPRETER_MODEL",
            "gemini-3.5-flash-lite",
        ),
        timeout_seconds=current_app.config.get(
            "GEMINI_TIMEOUT_SECONDS",
            30,
        ),
        request_log_dir=current_app.config.get("GEMINI_REQUEST_LOG_DIR"),
        rate_limit_cooldown_seconds=current_app.config.get(
            "GEMINI_RATE_LIMIT_COOLDOWN_SECONDS",
            60,
        ),
    )
    interpreted_state = validate_interpreted_requirements(
        decision,
        (current.get("trip") or {}).get("trip_days"),
        current_requirements=context["current_requirements"],
    )
    return decision, interpreted_state, pending


def _combined_pending_message(context):
    pending = context.get("pending_clarification")
    original = (
        str(pending.get("original_request") or "")
        if isinstance(pending, dict)
        else ""
    )
    answer = str(context.get("raw_user_message") or "")
    return f"{original} {answer}".strip()


def _has_local_adjustment(message, current):
    trip_days = int((current.get("trip") or {}).get("trip_days") or 0)
    try:
        parsed = parse_user_requirements(
            message,
            current_recommendation=current,
            trip_days=trip_days,
        )
    except ValueError:
        return False
    return bool(
        parsed.get("minimums")
        or parsed.get("exact_targets")
        or parsed.get("comparative")
        or parsed.get("segments")
        or parsed.get("maximum_price_aed") is not None
        or parsed.get("minimum_validity_days") is not None
        or parsed.get("restore_original")
        or parsed.get("reset_constraints")
    )


def _ensure_roaming_history(current):
    journey_id = session.get("roaming_history_journey_id")
    cursor_id = session.get("roaming_history_cursor_id")
    if journey_id and cursor_id:
        return journey_id, cursor_id
    entry = start_recommendation_history(current_user.id, current)
    session["roaming_history_journey_id"] = entry.journey_id
    session["roaming_history_cursor_id"] = entry.id
    return entry.journey_id, entry.id


def _restore_roaming_history_entry(entry, message, conversation, action):
    recommendation = entry.recommendation()
    if action == "original":
        reply = "Restored the original package recommendation."
    else:
        reply = "Restored the previous package recommendation."
    recommendation["modification_summary"] = reply
    recommendation["chat_message"] = reply
    session["roaming_current_recommendation"] = recommendation
    session["roaming_history_cursor_id"] = entry.id
    session["roaming_conversation"] = _append_roaming_conversation(
        conversation,
        message,
        reply,
    )
    session.modified = True
    return jsonify(
        {
            "ok": True,
            "response_type": "recommendation",
            "history_action": action,
            **recommendation,
        }
    )


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
    interaction_state = {}
    try:
        recommendation = build_recommendation(
            current_user,
            destination,
            payload.get("start_date"),
            payload.get("end_date"),
            interaction_state=interaction_state,
        )
    except ValueError as error:
        return jsonify({"ok": False, "message": str(error)}), 400
    history_entry = start_recommendation_history(current_user.id, recommendation)
    session["roaming_current_recommendation"] = recommendation
    session["roaming_conversation"] = []
    session["roaming_history_journey_id"] = history_entry.journey_id
    session["roaming_history_cursor_id"] = history_entry.id
    session.pop(ROAMING_GEMINI_INTERACTION_KEY, None)
    session.pop(ROAMING_PENDING_CLARIFICATION_KEY, None)
    if interaction_state.get("interaction_id"):
        session[ROAMING_GEMINI_INTERACTION_KEY] = interaction_state[
            "interaction_id"
        ]
    session[ROAMING_PLANNER_INITIALIZED_KEY] = bool(
        interaction_state.get("interaction_id")
    )
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
    journey_id, cursor_id = _ensure_roaming_history(current)
    intent = classify_roaming_chat_intent(message)
    if intent["kind"] == "greeting":
        reply = intent["reply"]
        session["roaming_conversation"] = _append_roaming_conversation(
            conversation,
            message,
            reply,
        )
        session.modified = True
        return jsonify(
            {
                "ok": True,
                "response_type": "message",
                "message": reply,
                "recommendation_id": current["recommendation_id"],
            }
        )
    if intent["kind"] == "original":
        original = get_original_history_entry(current_user.id, journey_id)
        if original is not None:
            return _restore_roaming_history_entry(
                original,
                message,
                conversation,
                "original",
            )
    if intent["kind"] == "previous":
        previous = get_previous_history_entry(
            current_user.id,
            journey_id,
            cursor_id,
        )
        if previous is not None:
            return _restore_roaming_history_entry(
                previous,
                message,
                conversation,
                "previous",
            )
        reply = "You are already viewing the earliest recommendation in this path."
        session["roaming_conversation"] = _append_roaming_conversation(
            conversation,
            message,
            reply,
        )
        session.modified = True
        return jsonify(
            {
                "ok": True,
                "response_type": "message",
                "message": reply,
                "recommendation_id": current["recommendation_id"],
            }
        )
    interaction_state = {}
    interpreted_state = None
    decision = None
    pending = None
    force_python_fallback = False
    upstream_rate_limited = False
    effective_message = message
    api_key = current_app.config.get("GEMINI_API_KEY", "")
    if api_key:
        try:
            decision, interpreted_state, pending = (
                _interpret_roaming_refinement(message, current)
            )
        except (GeminiRateLimited, GeminiUnavailable, ValueError) as error:
            upstream_rate_limited = isinstance(error, GeminiRateLimited)
            force_python_fallback = True
            LOGGER.warning(
                "Roaming interpreter fallback activated type=%s rate_limited=%s",
                type(error).__name__,
                upstream_rate_limited,
            )
            context, pending = _roaming_interpreter_context(message, current)
            decision = interpret_requirements_locally(context)
            if decision is not None:
                interpreted_state = validate_interpreted_requirements(
                    decision,
                    (current.get("trip") or {}).get("trip_days"),
                    current_requirements=context["current_requirements"],
                )
            else:
                effective_message = _combined_pending_message(context)
                if not _has_local_adjustment(effective_message, current):
                    session.pop(ROAMING_PENDING_CLARIFICATION_KEY, None)
                    prefix = (
                        "The Gemini request limit was reached. "
                        if upstream_rate_limited
                        else ""
                    )
                    reply = (
                        f"{prefix}I can still adjust the plan locally. "
                        "Should I change data, local minutes, international "
                        "minutes, SMS, price, or validity?"
                    )
                    session["roaming_conversation"] = (
                        _append_roaming_conversation(
                            conversation,
                            message,
                            reply,
                        )
                    )
                    session.modified = True
                    return jsonify(
                        {
                            "ok": True,
                            "response_type": "message",
                            "clarification_required": True,
                            "message": reply,
                            "recommendation_id": current[
                                "recommendation_id"
                            ],
                        }
                    )
    else:
        force_python_fallback = True
        context, pending = _roaming_interpreter_context(message, current)
        decision = interpret_requirements_locally(context)
        if decision is not None:
            interpreted_state = validate_interpreted_requirements(
                decision,
                (current.get("trip") or {}).get("trip_days"),
                current_requirements=context["current_requirements"],
            )
        else:
            effective_message = _combined_pending_message(context)

    if decision is not None and decision.clarification_required:
        if pending:
            pending["prior_answers"] = [
                *(pending.get("prior_answers") or []),
                message[:500],
            ][-4:]
        else:
            pending = {
                "original_request": message[:500],
                "prior_answers": [],
            }
        session[ROAMING_PENDING_CLARIFICATION_KEY] = pending
        prefix = (
            "The Gemini request limit was reached, but I can continue "
            "locally. "
            if upstream_rate_limited
            else ""
        )
        reply = f"{prefix}{decision.clarification_question}"
        session["roaming_conversation"] = _append_roaming_conversation(
            conversation,
            message,
            reply,
        )
        session.modified = True
        return jsonify(
            {
                "ok": True,
                "response_type": "message",
                "clarification_required": True,
                "message": reply,
                "recommendation_id": current["recommendation_id"],
            }
        )
    session.pop(ROAMING_PENDING_CLARIFICATION_KEY, None)

    try:
        recommendation = build_recommendation(
            current_user,
            destination,
            trip.get("start_date"),
            trip.get("end_date"),
            latest_message=effective_message,
            current_recommendation=current,
            conversation=conversation,
            previous_interaction_id=session.get(
                ROAMING_GEMINI_INTERACTION_KEY
            ),
            interaction_state=interaction_state,
            interpreted_state=interpreted_state,
            force_python_fallback=force_python_fallback,
            upstream_gemini_rate_limited=upstream_rate_limited,
        )
    except ValueError as error:
        return jsonify({"ok": False, "message": str(error)}), 400
    assistant_message = (
        recommendation.get("chat_message")
        or recommendation.get("modification_summary")
        or recommendation.get("tradeoff_summary")
        or recommendation["reason"]
    )
    if recommendation["recommendation_id"] != current["recommendation_id"]:
        history_entry = append_recommendation_history(
            current_user.id,
            journey_id,
            cursor_id,
            recommendation,
        )
        session["roaming_history_cursor_id"] = history_entry.id
    session["roaming_conversation"] = _append_roaming_conversation(
        conversation,
        message,
        assistant_message,
    )
    session["roaming_current_recommendation"] = recommendation
    if interaction_state.get("reset_conversation"):
        session.pop(ROAMING_GEMINI_INTERACTION_KEY, None)
        session[ROAMING_PLANNER_INITIALIZED_KEY] = False
    elif interaction_state.get("interaction_id"):
        session[ROAMING_GEMINI_INTERACTION_KEY] = interaction_state[
            "interaction_id"
        ]
        session[ROAMING_PLANNER_INITIALIZED_KEY] = True
    session.modified = True
    return jsonify(
        {"ok": True, "response_type": "recommendation", **recommendation}
    )


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
    session.pop("roaming_history_journey_id", None)
    session.pop("roaming_history_cursor_id", None)
    session.pop(ROAMING_GEMINI_INTERACTION_KEY, None)
    session.pop(ROAMING_PLANNER_INITIALIZED_KEY, None)
    session.pop(ROAMING_PENDING_CLARIFICATION_KEY, None)
    session.modified = True
    clear_recommendation_history(current_user.id)
    seed_database()
    return jsonify({"ok": True, "message": "Account data has been restored."})
