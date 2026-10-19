from collections.abc import Iterator

from sqlalchemy import Engine, text
from sqlmodel import Session, SQLModel, create_engine

from app.config import DATABASE_URL

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    add_missing_columns(engine)


def add_missing_columns(target: Engine) -> None:
    """Poor man's migration for SQLite: add columns the models have and the tables lack.

    create_all never alters existing tables, and a hackathon adds columns daily.
    Only additive changes are handled; renames and drops need a manual step.
    """
    if not target.dialect.name.startswith("sqlite"):
        return
    with target.begin() as con:
        for table in SQLModel.metadata.sorted_tables:
            existing = {row[1] for row in con.execute(text(f'PRAGMA table_info("{table.name}")'))}
            if not existing:
                continue
            for col in table.columns:
                if col.name in existing:
                    continue
                ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col.type.compile(target.dialect)}'
                if col.default is not None and col.default.is_scalar:
                    ddl += f" DEFAULT '{col.default.arg}'"
                elif col.type.python_type is dict:
                    ddl += " DEFAULT '{}'"
                con.execute(text(ddl))


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
