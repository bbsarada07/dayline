"""Database engine and session dependency."""

from collections.abc import Iterator

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from app.config import settings

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False, "timeout": 15},
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


def create_tables() -> None:
    # Import so every table is registered on the metadata.
    from app import models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    _add_missing_columns()


def _add_missing_columns() -> None:
    """create_all makes new tables but never changes existing ones: add columns added since."""
    added = {"student": {"omi_uid": "VARCHAR"}}  # Phase 8
    with engine.begin() as connection:
        for table, columns in added.items():
            have = {row[1] for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")}
            for name, sql_type in columns.items():
                if have and name not in have:
                    connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")
                    connection.exec_driver_sql(f"CREATE UNIQUE INDEX IF NOT EXISTS ix_{table}_{name} ON {table} ({name})")


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
