"""Small, idempotent schema upgrades for the project's SQLite database."""

from sqlalchemy import inspect, text

from .extensions import db


ROAMING_PACKAGE_COLUMNS = {
    "package_code": "VARCHAR(40)",
    "family": "VARCHAR(80)",
    "category": "VARCHAR(40)",
    "price_aed": "NUMERIC(10, 2)",
    "data_gb": "NUMERIC(10, 2)",
    "local_minutes": "INTEGER",
    "international_minutes": "INTEGER",
    "sms": "INTEGER",
    "coverage_scope": "VARCHAR(40) DEFAULT 'ALL_DESTINATIONS'",
    "repeatable": "BOOLEAN DEFAULT 1",
    "stackable": "BOOLEAN DEFAULT 1",
    "created_at": "DATETIME",
}


def upgrade_sqlite_schema():
    """Add missing package columns without replacing any existing table or row."""

    if db.engine.dialect.name != "sqlite":
        return

    inspector = inspect(db.engine)
    if "roaming_package" not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns("roaming_package")}
    with db.engine.begin() as connection:
        for name, definition in ROAMING_PACKAGE_COLUMNS.items():
            if name not in existing:
                connection.execute(
                    text(f'ALTER TABLE roaming_package ADD COLUMN "{name}" {definition}')
                )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "ix_roaming_package_package_code ON roaming_package (package_code)"
            )
        )
