import json

from app import DESTINATIONS, seed_database
from app.extensions import db
from app.models import BillRecord, ComplaintTicket, DiagnosticResult, RoamingPackage, User


def test_database_seeding(app):
    with app.app_context():
        demo = User.query.filter_by(email="demo@prototype.local").first()
        assert demo is not None
        assert demo.full_name == "Customer Account"
        assert demo.check_password("Demo123!")
        assert BillRecord.query.filter_by(user_id=demo.id).count() >= 1
        assert ComplaintTicket.query.filter_by(user_id=demo.id).count() >= 1
        assert DiagnosticResult.query.filter_by(user_id=demo.id).count() >= 1


def test_roaming_package_records_exist(app):
    with app.app_context():
        packages = RoamingPackage.query.filter_by(active=True).all()
        assert len(packages) == 5
        assert all("Partner" in package.preferred_network for package in packages)
        assert len(DESTINATIONS) == 32
        assert DESTINATIONS == sorted(DESTINATIONS)
        assert all(package.destinations == DESTINATIONS for package in packages)

        demo = User.query.filter_by(email="demo@prototype.local").first()
        diagnostic = DiagnosticResult.query.filter_by(user_id=demo.id).first()
        ticket = ComplaintTicket.query.filter_by(user_id=demo.id).first()
        demo.full_name = "Prototype Demo User"
        packages[0].supported_destinations = json.dumps(["Canada"])
        packages[0].preferred_network = "Demo Network A"
        diagnostic.location_label = "Downtown Dubai — demo location"
        ticket.location_label = "Dubai Marina — demo location"
        db.session.commit()
        seed_database()
        assert demo.full_name == "Customer Account"
        assert db.session.get(RoamingPackage, packages[0].id).destinations == DESTINATIONS
        assert db.session.get(RoamingPackage, packages[0].id).preferred_network == "Partner Network A"
        assert diagnostic.location_label == "Downtown Dubai"
        assert ticket.location_label == "Dubai Marina"
