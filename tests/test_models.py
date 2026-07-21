from app import DESTINATIONS, seed_database
from app.models import BillRecord, ComplaintTicket, DiagnosticResult, RoamingPackage, User


def test_database_seeding(app):
    with app.app_context():
        user = User.query.filter_by(email="aisha@example.test").one()
        assert user.full_name == "Aisha Noor"
        assert user.check_password("Demo123!")
        assert BillRecord.query.filter_by(user_id=user.id).count() >= 1
        assert ComplaintTicket.query.filter_by(user_id=user.id).count() >= 1
        assert DiagnosticResult.query.filter_by(user_id=user.id).count() >= 1


def test_roaming_package_records_exist(app):
    with app.app_context():
        packages = RoamingPackage.query.filter_by(active=True).all()
        assert len(packages) == 42
        assert len({package.package_code for package in packages}) == 42
        assert all(
            package.preferred_network == "Automatic partner selection"
            for package in packages
        )
        assert len(DESTINATIONS) == 32
        assert DESTINATIONS == sorted(DESTINATIONS)
        assert all(package.destinations == DESTINATIONS for package in packages)

        before = (User.query.count(), RoamingPackage.query.count())
        seed_database()
        assert (User.query.count(), RoamingPackage.query.count()) == before
