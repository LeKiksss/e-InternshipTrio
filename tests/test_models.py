import json

from app import DESTINATIONS, seed_database
from app.extensions import db
from app.models import BillRecord, ComplaintTicket, DiagnosticResult, RoamingPackage, User


def test_database_seeding(app):
    with app.app_context():
        demo = User.query.filter_by(email="demo@prototype.local").first()
        assert demo is not None
        assert demo.check_password("Demo123!")
        assert BillRecord.query.filter_by(user_id=demo.id).count() >= 1
        assert ComplaintTicket.query.filter_by(user_id=demo.id).count() >= 1
        assert DiagnosticResult.query.filter_by(user_id=demo.id).count() >= 1


def test_roaming_package_records_exist(app):
    with app.app_context():
        packages = RoamingPackage.query.filter_by(active=True).all()
        assert len(packages) == 5
        assert all("Demo" in package.preferred_network or "Preferred Partner" in package.preferred_network for package in packages)
        assert len(DESTINATIONS) == 32
        assert DESTINATIONS == sorted(DESTINATIONS)
        assert all(package.destinations == DESTINATIONS for package in packages)

        packages[0].supported_destinations = json.dumps(["Canada"])
        db.session.commit()
        seed_database()
        assert db.session.get(RoamingPackage, packages[0].id).destinations == DESTINATIONS
