"""Idempotent schema migration for evaluation persistence."""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "eval_results.db"


def migrate() -> None:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='runs'")
        if not cursor.fetchone():
            conn.close()
            return

        existing = {row[1] for row in cursor.execute("PRAGMA table_info(runs)").fetchall()}

        if "status" not in existing:
            cursor.execute(
                "ALTER TABLE runs ADD COLUMN status TEXT NOT NULL DEFAULT 'completed'"
            )
        if "completed_at" not in existing:
            cursor.execute("ALTER TABLE runs ADD COLUMN completed_at TEXT")
        if "error" not in existing:
            cursor.execute("ALTER TABLE runs ADD COLUMN error TEXT")

        cursor.execute(
            "UPDATE runs SET completed_at = timestamp WHERE completed_at IS NULL"
        )
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
