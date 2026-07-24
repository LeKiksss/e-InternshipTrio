from datetime import date

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import ComplaintTicket, RoamingPackage, User, UserMonthlyUsage
from app.seed_data import MONTHLY_USAGE, PACKAGE_CATALOGUE, SEEDED_USERS, seed_all


SEEDED_EMAILS = {email for _name, email, _phone in SEEDED_USERS}

EXPECTED_USERS = {
    "aisha@example.test": ("Aisha Noor", "+971500000101"),
    "omar@example.test": ("Omar Hassan", "+971500000102"),
    "layla@example.test": ("Layla Faris", "+971500000103"),
    "yusuf@example.test": ("Yusuf Kareem", "+971500000104"),
}

EXPECTED_MONTHLY_USAGE = {
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

EXPECTED_PACKAGE_FAMILIES = (
    ("ESS", "Roam Essentials", "BUDGET_BALANCED", 11, (
        (1, 15, 0.5, 15, 5, 5), (3, 35, 1.5, 45, 15, 15),
        (7, 69, 3, 100, 35, 30), (10, 95, 5, 150, 50, 45),
        (14, 129, 7, 210, 70, 60), (30, 249, 15, 450, 150, 120),
    )),
    ("RLH", "Roam with Balance", "BALANCED", 12, (
        (1, 29, 1, 40, 20, 10), (3, 69, 3, 120, 60, 30),
        (7, 149, 8, 300, 150, 75), (10, 199, 12, 450, 225, 100),
        (14, 269, 18, 650, 325, 150), (30, 499, 40, 1400, 700, 300),
    )),
    ("PRE", "Roam Premium", "PREMIUM_BALANCED", 13, (
        (1, 59, 3, 100, 50, 25), (3, 139, 8, 300, 150, 75),
        (7, 299, 20, 700, 350, 150), (10, 399, 30, 1000, 500, 250),
        (14, 549, 45, 1500, 750, 350), (30, 999, 100, 3200, 1600, 700),
    )),
    ("DF", "Data First", "DATA_MAXIMUM", 14, (
        (1, 39, 5, 5, 0, 0), (3, 99, 15, 15, 0, 0),
        (7, 219, 35, 30, 5, 5), (10, 299, 50, 50, 10, 10),
        (14, 399, 75, 75, 15, 15), (30, 749, 160, 150, 30, 30),
    )),
    ("DP", "Data Plus", "DATA_FOCUSED", 15, (
        (1, 39, 3, 25, 10, 10), (3, 109, 10, 90, 30, 25),
        (7, 239, 25, 250, 80, 60), (10, 329, 40, 350, 120, 90),
        (14, 449, 60, 500, 180, 120), (30, 849, 130, 1100, 400, 250),
    )),
    ("VF", "Voice First", "VOICE_MAXIMUM", 16, (
        (1, 35, 0.25, 200, 100, 25), (3, 89, 0.75, 600, 300, 75),
        (7, 199, 1.5, 1400, 700, 150), (10, 279, 2, 2000, 1000, 220),
        (14, 379, 3, 2800, 1400, 300), (30, 699, 6, 6000, 3000, 600),
    )),
    ("VP", "Voice Plus", "VOICE_FOCUSED", 17, (
        (1, 39, 1, 150, 75, 20), (3, 99, 3, 450, 225, 60),
        (7, 219, 7, 1100, 550, 140), (10, 299, 10, 1600, 800, 200),
        (14, 409, 15, 2300, 1150, 280), (30, 779, 32, 5000, 2500, 600),
    )),
)


def test_exact_seed_counts_credentials_and_hashes(app):
    with app.app_context():
        users = User.query.filter(User.email.in_(SEEDED_EMAILS)).all()
        assert len(users) == 4
        assert UserMonthlyUsage.query.filter(
            UserMonthlyUsage.user_id.in_([user.id for user in users])
        ).count() == 24
        assert RoamingPackage.query.count() == 42
        assert len(PACKAGE_CATALOGUE) == 42
        for user in users:
            assert (user.full_name, user.phone_number) == EXPECTED_USERS[user.email]
            assert len(user.monthly_usage) == 6
            assert user.check_password("Demo123!")
            assert user.password_hash != "Demo123!"
            assert "Demo123!" not in user.password_hash


def test_every_seeded_usage_value_matches_the_required_raw_history(app):
    with app.app_context():
        observed = {}
        for email in EXPECTED_MONTHLY_USAGE:
            user = User.query.filter_by(email=email).one()
            observed[email] = tuple(
                (
                    row.usage_month.isoformat(),
                    float(row.data_gb),
                    row.local_minutes,
                    row.international_minutes,
                    row.sms,
                )
                for row in user.monthly_usage
            )
        assert observed == EXPECTED_MONTHLY_USAGE


def test_every_seeded_package_fact_matches_the_required_catalogue(app):
    expected = {}
    for prefix, family, category, activation_family, variants in EXPECTED_PACKAGE_FAMILIES:
        for validity, price, data, local, international, sms in variants:
            code = f"{prefix}-{validity}D"
            expected[code] = (
                f"{family} {validity} {'Day' if validity == 1 else 'Days'}",
                family,
                category,
                validity,
                float(price),
                float(data),
                local,
                international,
                sms,
                "ALL_DESTINATIONS",
                f"*170*{activation_family}*{validity:02d}#",
                "Automatic partner selection",
                True,
                True,
                True,
            )

    with app.app_context():
        observed = {
            row.package_code: (
                row.name,
                row.family,
                row.category,
                row.validity_days,
                float(row.price_aed),
                float(row.data_gb),
                row.local_minutes,
                row.international_minutes,
                row.sms,
                row.coverage_scope,
                row.activation_code,
                row.preferred_network,
                row.repeatable,
                row.stackable,
                row.active,
            )
            for row in RoamingPackage.query.order_by(RoamingPackage.package_code)
        }
        assert observed == expected


def test_seed_is_idempotent_and_catalogue_codes_are_unique(app):
    with app.app_context():
        first = seed_all()
        snapshot = (
            User.query.count(),
            UserMonthlyUsage.query.count(),
            RoamingPackage.query.count(),
        )
        second = seed_all()
        assert snapshot == (
            User.query.count(),
            UserMonthlyUsage.query.count(),
            RoamingPackage.query.count(),
        )
        assert first == second == {
            "seeded_users": 4,
            "usage_rows": 24,
            "active_packages": 42,
        }
        codes = [row.package_code for row in RoamingPackage.query.all()]
        assert len(codes) == len(set(codes)) == 42


def test_existing_unrelated_records_survive_reseeding(app):
    with app.app_context():
        user = User(
            full_name="Team Member",
            email="team.member@example.test",
            phone_number="+971500009999",
        )
        user.set_password("Portable123!")
        db.session.add(user)
        db.session.flush()
        ticket = ComplaintTicket(
            user_id=user.id,
            ticket_number="ET-KEEP-0001",
            category="Billing",
            severity="Low",
            summary="This record must remain present after reseeding.",
            expected_resolution="Within 48 hours",
        )
        db.session.add(ticket)
        db.session.commit()

        seed_all()
        assert User.query.filter_by(email="team.member@example.test").one().id == user.id
        assert ComplaintTicket.query.filter_by(ticket_number="ET-KEEP-0001").one().id == ticket.id


def test_raw_omar_march_values_are_preserved(app):
    with app.app_context():
        omar = User.query.filter_by(email="omar@example.test").one()
        march = UserMonthlyUsage.query.filter_by(
            user_id=omar.id, usage_month=date(2026, 3, 1)
        ).one()
        assert float(march.data_gb) == 61.0
        assert march.local_minutes == 1250
        assert march.international_minutes == 780
        assert march.sms == 180
        assert MONTHLY_USAGE["omar@example.test"][2] == (
            "2026-03-01",
            61.0,
            1250,
            780,
            180,
        )


def test_schema_has_no_stored_profile_classification_or_expected_average(app):
    with app.app_context():
        inspector = inspect(db.engine)
        user_columns = {column["name"] for column in inspector.get_columns("user")}
        usage_columns = {
            column["name"] for column in inspector.get_columns("user_monthly_usage")
        }
        forbidden = {
            "archetype",
            "usage_pattern",
            "trend_label",
            "expected_weighted_average",
            "weighted_monthly_estimate",
        }
        assert forbidden.isdisjoint(user_columns)
        assert forbidden.isdisjoint(usage_columns)


def test_user_month_and_negative_usage_constraints(app):
    with app.app_context():
        aisha = User.query.filter_by(email="aisha@example.test").one()
        duplicate = UserMonthlyUsage(
            user_id=aisha.id,
            usage_month=date(2026, 1, 1),
            data_gb=1,
            local_minutes=1,
            international_minutes=1,
            sms=1,
        )
        db.session.add(duplicate)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()

        negative = UserMonthlyUsage(
            user_id=aisha.id,
            usage_month=date(2027, 1, 1),
            data_gb=-1,
            local_minutes=0,
            international_minutes=0,
            sms=0,
        )
        db.session.add(negative)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()
