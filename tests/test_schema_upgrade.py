from flask import Flask
from sqlalchemy import inspect, text

from app.extensions import db
from app.schema_upgrade import ROAMING_PACKAGE_COLUMNS, upgrade_sqlite_schema


def test_sqlite_upgrade_is_additive_idempotent_and_preserves_rows(tmp_path):
    database = tmp_path / "legacy.sqlite"
    application = Flask(__name__)
    application.config.update(
        TESTING=True,
        SECRET_KEY="schema-test",
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{database.as_posix()}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(application)

    with application.app_context():
        with db.engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE roaming_package ("
                    "id INTEGER PRIMARY KEY, name VARCHAR(100) NOT NULL UNIQUE)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO roaming_package (id, name) "
                    "VALUES (7, 'Existing Package')"
                )
            )

        upgrade_sqlite_schema()
        upgrade_sqlite_schema()

        columns = {
            column["name"] for column in inspect(db.engine).get_columns("roaming_package")
        }
        assert set(ROAMING_PACKAGE_COLUMNS).issubset(columns)
        with db.engine.connect() as connection:
            preserved = connection.execute(
                text("SELECT id, name FROM roaming_package")
            ).one()
        assert tuple(preserved) == (7, "Existing Package")
