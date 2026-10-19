import sqlite3

from sqlalchemy import create_engine, text

from app.db import add_missing_columns


def test_init_adds_columns_that_an_older_database_lacks(tmp_path) -> None:
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as con:
        con.execute(
            "CREATE TABLE user (handle TEXT PRIMARY KEY, display_name TEXT NOT NULL, email TEXT NOT NULL,"
            " groknet_token TEXT NOT NULL, webhook_url TEXT NOT NULL, webhook_key TEXT NOT NULL,"
            " created_at TIMESTAMP NOT NULL)"
        )
    engine = create_engine(f"sqlite:///{path}")

    add_missing_columns(engine)

    with engine.connect() as con:
        cols = {row[1] for row in con.execute(text("PRAGMA table_info(user)"))}
    assert "profile" in cols
