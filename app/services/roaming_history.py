"""Persistent navigation history for validated roaming recommendations."""

import json
from uuid import uuid4

from sqlalchemy import func

from app.extensions import db
from app.models import RoamingRecommendationHistory


def start_recommendation_history(user_id, recommendation):
    RoamingRecommendationHistory.query.filter_by(user_id=user_id).delete()
    journey_id = uuid4().hex
    entry = RoamingRecommendationHistory(
        user_id=user_id,
        journey_id=journey_id,
        sequence_number=0,
        previous_history_id=None,
        recommendation_id=recommendation["recommendation_id"],
        recommendation_json=json.dumps(recommendation, separators=(",", ":")),
    )
    db.session.add(entry)
    db.session.commit()
    return entry


def append_recommendation_history(
    user_id,
    journey_id,
    previous_history_id,
    recommendation,
):
    last_sequence = (
        db.session.query(func.max(RoamingRecommendationHistory.sequence_number))
        .filter_by(user_id=user_id, journey_id=journey_id)
        .scalar()
    )
    entry = RoamingRecommendationHistory(
        user_id=user_id,
        journey_id=journey_id,
        sequence_number=int(last_sequence or 0) + 1,
        previous_history_id=previous_history_id,
        recommendation_id=recommendation["recommendation_id"],
        recommendation_json=json.dumps(recommendation, separators=(",", ":")),
    )
    db.session.add(entry)
    db.session.commit()
    return entry


def get_history_entry(user_id, journey_id, history_id):
    if not journey_id or not history_id:
        return None
    return RoamingRecommendationHistory.query.filter_by(
        id=history_id,
        user_id=user_id,
        journey_id=journey_id,
    ).first()


def get_original_history_entry(user_id, journey_id):
    if not journey_id:
        return None
    return RoamingRecommendationHistory.query.filter_by(
        user_id=user_id,
        journey_id=journey_id,
        sequence_number=0,
    ).first()


def get_previous_history_entry(user_id, journey_id, history_id):
    current = get_history_entry(user_id, journey_id, history_id)
    if current is None or current.previous_history_id is None:
        return None
    return get_history_entry(
        user_id,
        journey_id,
        current.previous_history_id,
    )


def clear_recommendation_history(user_id):
    RoamingRecommendationHistory.query.filter_by(user_id=user_id).delete()
    db.session.commit()
