"""
Lightweight schema migration for SQLite.

SQLite doesn't support ALTER TABLE ADD COLUMN IF NOT EXISTS, so we check
information_schema manually before adding each column.
"""
import os
from pathlib import Path
from sqlalchemy import text
from src.db.models import get_engine


NEW_COLUMNS = [
    # (table, column_name, column_definition)
    ("jobs", "responded_at",    "DATETIME"),
    ("jobs", "gap_skills",      "TEXT"),
    ("jobs", "level",           "VARCHAR"),
    ("jobs", "required_skills", "TEXT"),
    ("jobs", "preferred_skills","TEXT"),
    ("jobs", "skill_categories","TEXT"),
]


def migrate(db_path: str | None = None) -> list[str]:
    """
    Add any missing columns to the existing DB.
    Returns list of column names that were added.
    """
    if db_path is None:
        db_path = os.getenv("DB_PATH", "data/jobs.db")

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = get_engine(db_path)
    added = []

    with engine.connect() as conn:
        for table, col, col_def in NEW_COLUMNS:
            # Get existing columns
            result = conn.execute(text(f"PRAGMA table_info({table})"))
            existing = {row[1] for row in result}
            if col not in existing:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}"))
                conn.commit()
                added.append(f"{table}.{col}")

    return added
