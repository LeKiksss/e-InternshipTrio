"""Idempotent seed data for local development and repeatable team setup."""

import json
from datetime import date, datetime, timedelta

from .extensions import db
from .models import (
    BillRecord,
    ComplaintTicket,
    DiagnosticResult,
    RoamingPackage,
    User,
    UserMonthlyUsage,
)


SEEDED_USERS = (
    ("Aisha Noor", "aisha@example.test", "+971500000101"),
    ("Omar Hassan", "omar@example.test", "+971500000102"),
    ("Layla Faris", "layla@example.test", "+971500000103"),
    ("Yusuf Kareem", "yusuf@example.test", "+971500000104"),
)
SEEDED_PASSWORD = "Demo123!"

MONTHLY_USAGE = {
    "aisha@example.test": (
        ("2026-01-01", 4.2, 110, 18, 12),
        ("2026-02-01", 4.5, 115, 20, 10),
        ("2026-03-01", 4.3, 108, 19, 11),
        ("2026-04-01", 4.6, 117, 21, 13),
        ("2026-05-01", 4.4, 112, 20, 12),
        ("2026-06-01", 4.7, 119, 22, 14),
    ),
    "omar@example.test": (
        ("2026-01-01", 13.5, 310, 95, 34),
        ("2026-02-01", 14.2, 325, 100, 36),
        ("2026-03-01", 61.0, 1250, 780, 180),
        ("2026-04-01", 14.8, 330, 105, 35),
        ("2026-05-01", 15.1, 340, 110, 38),
        ("2026-06-01", 15.6, 350, 112, 40),
    ),
    "layla@example.test": (
        ("2026-01-01", 25.0, 130, 45, 20),
        ("2026-02-01", 29.0, 135, 48, 22),
        ("2026-03-01", 34.0, 140, 50, 24),
        ("2026-04-01", 39.0, 145, 53, 25),
        ("2026-05-01", 45.0, 150, 55, 27),
        ("2026-06-01", 52.0, 155, 58, 28),
    ),
    "yusuf@example.test": (
        ("2026-01-01", 8.5, 900, 420, 70),
        ("2026-02-01", 8.2, 830, 390, 66),
        ("2026-03-01", 7.8, 760, 350, 62),
        ("2026-04-01", 7.4, 690, 320, 58),
        ("2026-05-01", 7.0, 620, 285, 54),
        ("2026-06-01", 6.6, 560, 250, 50),
    ),
}


def _family_rows(family, category, prefix, family_number, rows):
    return [
        {
            "package_code": f"{prefix}-{days}D",
            "name": f"{family} {days} Day" if days == 1 else f"{family} {days} Days",
            "family": family,
            "category": category,
            "validity_days": days,
            "price_aed": price,
            "data_gb": data,
            "local_minutes": local,
            "international_minutes": international,
            "sms": sms,
            "activation_code": f"*170*{family_number}*{days:02d}#",
        }
        for days, price, data, local, international, sms in rows
    ]


PACKAGE_CATALOGUE = [
    *_family_rows(
        "Roam Essentials",
        "BUDGET_BALANCED",
        "ESS",
        11,
        (
            (1, 15, 0.5, 15, 5, 5),
            (3, 35, 1.5, 45, 15, 15),
            (7, 69, 3, 100, 35, 30),
            (10, 95, 5, 150, 50, 45),
            (14, 129, 7, 210, 70, 60),
            (30, 249, 15, 450, 150, 120),
        ),
    ),
    *_family_rows(
        "Roam Like Home",
        "BALANCED",
        "RLH",
        12,
        (
            (1, 29, 1, 40, 20, 10),
            (3, 69, 3, 120, 60, 30),
            (7, 149, 8, 300, 150, 75),
            (10, 199, 12, 450, 225, 100),
            (14, 269, 18, 650, 325, 150),
            (30, 499, 40, 1400, 700, 300),
        ),
    ),
    *_family_rows(
        "Roam Premium",
        "PREMIUM_BALANCED",
        "PRE",
        13,
        (
            (1, 59, 3, 100, 50, 25),
            (3, 139, 8, 300, 150, 75),
            (7, 299, 20, 700, 350, 150),
            (10, 399, 30, 1000, 500, 250),
            (14, 549, 45, 1500, 750, 350),
            (30, 999, 100, 3200, 1600, 700),
        ),
    ),
    *_family_rows(
        "Data First",
        "DATA_MAXIMUM",
        "DF",
        14,
        (
            (1, 39, 5, 5, 0, 0),
            (3, 99, 15, 15, 0, 0),
            (7, 219, 35, 30, 5, 5),
            (10, 299, 50, 50, 10, 10),
            (14, 399, 75, 75, 15, 15),
            (30, 749, 160, 150, 30, 30),
        ),
    ),
    *_family_rows(
        "Data Plus",
        "DATA_FOCUSED",
        "DP",
        15,
        (
            (1, 39, 3, 25, 10, 10),
            (3, 109, 10, 90, 30, 25),
            (7, 239, 25, 250, 80, 60),
            (10, 329, 40, 350, 120, 90),
            (14, 449, 60, 500, 180, 120),
            (30, 849, 130, 1100, 400, 250),
        ),
    ),
    *_family_rows(
        "Voice First",
        "VOICE_MAXIMUM",
        "VF",
        16,
        (
            (1, 35, 0.25, 200, 100, 25),
            (3, 89, 0.75, 600, 300, 75),
            (7, 199, 1.5, 1400, 700, 150),
            (10, 279, 2, 2000, 1000, 220),
            (14, 379, 3, 2800, 1400, 300),
            (30, 699, 6, 6000, 3000, 600),
        ),
    ),
    *_family_rows(
        "Voice Plus",
        "VOICE_FOCUSED",
        "VP",
        17,
        (
            (1, 39, 1, 150, 75, 20),
            (3, 99, 3, 450, 225, 60),
            (7, 219, 7, 1100, 550, 140),
            (10, 299, 10, 1600, 800, 200),
            (14, 409, 15, 2300, 1150, 280),
            (30, 779, 32, 5000, 2500, 600),
        ),
    ),
]

PACKAGE_NOTES = {
    "BUDGET_BALANCED": "Cost-conscious balanced coverage for lighter usage.",
    "BALANCED": "Balanced data, calling, and messaging coverage.",
    "PREMIUM_BALANCED": "High combined allowances for intensive mixed usage.",
    "DATA_MAXIMUM": "Maximum data with minimal calling allowances.",
    "DATA_FOCUSED": "Data-led coverage with practical voice allowances.",
    "VOICE_MAXIMUM": "Maximum local and international calling allowances.",
    "VOICE_FOCUSED": "Voice-led coverage with a useful data allowance.",
}


def seed_users():
    users = {}
    for full_name, email, phone_number in SEEDED_USERS:
        user = User.query.filter_by(email=email).first()
        if user is None:
            user = User(
                full_name=full_name,
                email=email,
                phone_number=phone_number,
                notification_preferences="Important updates",
                preferred_contact_method="SMS",
            )
            user.set_password(SEEDED_PASSWORD)
            db.session.add(user)
        else:
            user.full_name = full_name
            user.phone_number = phone_number
            if not user.check_password(SEEDED_PASSWORD):
                user.set_password(SEEDED_PASSWORD)
        users[email] = user

    db.session.flush()
    return users


def seed_user_monthly_usage(users=None):
    users = users or {email: User.query.filter_by(email=email).one() for email in MONTHLY_USAGE}
    for email, records in MONTHLY_USAGE.items():
        user = users[email]
        for month, data_gb, local, international, sms in records:
            usage_month = date.fromisoformat(month)
            row = UserMonthlyUsage.query.filter_by(
                user_id=user.id,
                usage_month=usage_month,
            ).first()
            if row is None:
                row = UserMonthlyUsage(user_id=user.id, usage_month=usage_month)
                db.session.add(row)
            row.data_gb = data_gb
            row.local_minutes = local
            row.international_minutes = international
            row.sms = sms


def _apply_package(row, definition, supported_destinations):
    row.package_code = definition["package_code"]
    row.name = definition["name"]
    row.family = definition["family"]
    row.category = definition["category"]
    row.validity_days = definition["validity_days"]
    row.price_aed = definition["price_aed"]
    row.data_gb = definition["data_gb"]
    row.local_minutes = definition["local_minutes"]
    row.international_minutes = definition["international_minutes"]
    row.sms = definition["sms"]
    row.sms_allowance = definition["sms"]
    row.coverage_scope = "ALL_DESTINATIONS"
    row.activation_code = definition["activation_code"]
    row.preferred_network = "Automatic partner selection"
    row.repeatable = True
    row.stackable = True
    row.active = True
    if row.created_at is None:
        row.created_at = datetime.now()
    row.updated_at = datetime.now()

    # Keep legacy columns coherent while the existing database is upgraded in place.
    row.supported_destinations = supported_destinations
    row.price = float(definition["price_aed"])
    row.currency = "AED"
    row.data_allowance = f'{definition["data_gb"]:g} GB'
    row.voice_minutes = definition["local_minutes"]
    row.activation_instructions = (
        "Activate packages in the displayed order and confirm each carrier response before continuing."
    )
    row.notes = PACKAGE_NOTES[definition["category"]]


def seed_roaming_packages():
    from app import DESTINATIONS

    supported_destinations = json.dumps(DESTINATIONS)
    definitions_by_code = {item["package_code"]: item for item in PACKAGE_CATALOGUE}
    existing_codes = {
        row.package_code
        for row in RoamingPackage.query.filter(RoamingPackage.package_code.is_not(None)).all()
    }
    available = [item for item in PACKAGE_CATALOGUE if item["package_code"] not in existing_codes]

    # Preserve legacy row identities by upgrading them into catalogue rows.
    legacy_rows = (
        RoamingPackage.query.filter(RoamingPackage.package_code.is_(None))
        .order_by(RoamingPackage.id)
        .all()
    )
    for row, definition in zip(legacy_rows, available):
        _apply_package(row, definition, supported_destinations)

    db.session.flush()
    for package_code, definition in definitions_by_code.items():
        row = RoamingPackage.query.filter_by(package_code=package_code).first()
        if row is None:
            row = RoamingPackage(package_code=package_code, name=definition["name"])
            db.session.add(row)
        _apply_package(row, definition, supported_destinations)


def seed_existing_account_data():
    user = User.query.filter_by(email="demo@prototype.local").first()
    if user is None:
        user = User(
            full_name="Customer Account",
            email="demo@prototype.local",
            phone_number="+971501234567",
            notification_preferences="Important updates",
            preferred_contact_method="SMS",
        )
        user.set_password("Demo123!")
        db.session.add(user)
        db.session.flush()
    elif user.full_name == "Prototype Demo User":
        user.full_name = "Customer Account"

    diagnostic = DiagnosticResult.query.filter_by(user_id=user.id).first()
    if diagnostic is None:
        db.session.add(
            DiagnosticResult(
                user_id=user.id,
                download_speed=172.4,
                upload_speed=29.8,
                latency=21,
                verdict="Excellent",
                location_label="Downtown Dubai",
                created_at=datetime.now() - timedelta(days=5),
            )
        )
    elif diagnostic.location_label == "Downtown Dubai — demo location":
        diagnostic.location_label = "Downtown Dubai"

    if BillRecord.query.filter_by(user_id=user.id).first() is None:
        db.session.add(
            BillRecord(
                user_id=user.id,
                total_amount=468,
                due_date=(datetime.now() + timedelta(days=5)).strftime("%d %b %Y"),
                data_charges=240,
                call_charges=72,
                roaming_charges=96,
                addon_charges=60,
                anomaly_summary=(
                    "Bill is 28% higher than usual; roaming charges caused most of the increase."
                ),
            )
        )

    ticket = ComplaintTicket.query.filter_by(user_id=user.id).first()
    if ticket is None:
        db.session.add(
            ComplaintTicket(
                user_id=user.id,
                ticket_number="ET-2026-00142",
                category="Network",
                severity="High",
                summary="Intermittent mobile data near the Marina during afternoon hours.",
                status="Assigned",
                latest_update="Assigned to Network Operations for an area coverage review.",
                expected_resolution="Within 24 hours",
                assigned_department="Network Operations",
                location_label="Dubai Marina",
            )
        )
    elif ticket.location_label == "Dubai Marina — demo location":
        ticket.location_label = "Dubai Marina"


def seed_primary_account_activity(user):
    """Give the primary seeded sign-in a complete dashboard without altering other users."""

    if DiagnosticResult.query.filter_by(user_id=user.id).first() is None:
        db.session.add(
            DiagnosticResult(
                user_id=user.id,
                download_speed=172.4,
                upload_speed=29.8,
                latency=21,
                verdict="Excellent",
                location_label="Downtown Dubai",
                created_at=datetime.now() - timedelta(days=5),
            )
        )
    if BillRecord.query.filter_by(user_id=user.id).first() is None:
        db.session.add(
            BillRecord(
                user_id=user.id,
                total_amount=468,
                due_date=(datetime.now() + timedelta(days=5)).strftime("%d %b %Y"),
                data_charges=240,
                call_charges=72,
                roaming_charges=96,
                addon_charges=60,
                anomaly_summary="Bill is 28% higher than usual; roaming charges caused most of the increase.",
            )
        )
    if ComplaintTicket.query.filter_by(user_id=user.id).first() is None:
        db.session.add(
            ComplaintTicket(
                user_id=user.id,
                ticket_number="ET-2026-00242",
                category="Network",
                severity="High",
                summary="Intermittent mobile data near the Marina during afternoon hours.",
                status="Assigned",
                latest_update="Assigned to Network Operations for an area coverage review.",
                expected_resolution="Within 24 hours",
                assigned_department="Network Operations",
                location_label="Dubai Marina",
            )
        )


def seed_all():
    seed_existing_account_data()
    users = seed_users()
    seed_primary_account_activity(users["aisha@example.test"])
    seed_user_monthly_usage(users)
    seed_roaming_packages()
    db.session.commit()

    seeded_ids = [user.id for user in users.values()]
    return {
        "seeded_users": User.query.filter(User.email.in_(MONTHLY_USAGE)).count(),
        "usage_rows": UserMonthlyUsage.query.filter(UserMonthlyUsage.user_id.in_(seeded_ids)).count(),
        "active_packages": RoamingPackage.query.filter_by(active=True).count(),
    }
