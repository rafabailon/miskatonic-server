"""SQLite connection and repository helpers for the local archive."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Any

from flask import Flask, current_app, g


@dataclass(frozen=True, slots=True)
class ArchiveEntry:
    id: int
    title: str
    category: str
    content: str
    sanity: int
    created_at: str
    updated_at: str

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation of the entry."""
        return {
            "id": self.id,
            "title": self.title,
            "category": self.category,
            "content": self.content,
            "sanity": self.sanity,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


SCHEMA = """
CREATE TABLE IF NOT EXISTS archive_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 120),
    category TEXT NOT NULL CHECK(length(category) BETWEEN 1 AND 40),
    content TEXT NOT NULL CHECK(length(content) BETWEEN 1 AND 10000),
    sanity INTEGER NOT NULL CHECK(sanity BETWEEN 0 AND 100),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_archive_entries_updated
    ON archive_entries(updated_at DESC, id DESC);
"""


def get_db() -> sqlite3.Connection:
    """Return a request-scoped SQLite connection with safe row access."""
    if "db" not in g:
        database = current_app.config["DATABASE"]
        if database == ":memory:":
            if not hasattr(current_app, "_miskatonic_memory_db"):
                connection = sqlite3.connect(
                    ":memory:",
                    timeout=5.0,
                    isolation_level=None,
                    check_same_thread=False,
                )
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA foreign_keys = ON")
                connection.execute("PRAGMA busy_timeout = 5000")
                connection.execute("PRAGMA synchronous = NORMAL")
                current_app._miskatonic_memory_db = connection  # type: ignore[attr-defined]
            g.db = current_app._miskatonic_memory_db  # type: ignore[attr-defined]
        else:
            connection = sqlite3.connect(
                database,
                timeout=5.0,
                isolation_level=None,
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            connection.execute("PRAGMA synchronous = NORMAL")
            g.db = connection
    return g.db


def close_db(_error: BaseException | None = None) -> None:
    connection = g.pop("db", None)
    if connection is not None and current_app.config.get("DATABASE") != ":memory:":
        connection.close()
    elif connection is not None and current_app.config.get("DATABASE") == ":memory:":
        # Keep in-memory database alive for the app lifetime.
        g.pop("db", None)


def init_db(app: Flask) -> None:
    """Create the schema at startup; the database file is never exposed over HTTP."""
    database_path = app.config["DATABASE"]
    if database_path != ":memory:":
        resolved_path = Path(database_path).expanduser().resolve()
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        app.config["DATABASE"] = str(resolved_path)
    with app.app_context():
        connection = get_db()
        if database_path != ":memory:":
            # WAL keeps readers available while a write is in progress.
            try:
                connection.execute("PRAGMA journal_mode = WAL")
            except sqlite3.Error:
                app.logger.debug("Could not enable WAL mode.")
        connection.executescript(SCHEMA)


def list_entries(query: str = "", limit: int | None = 100) -> list[ArchiveEntry]:
    """Return entries ordered by most recently updated.

    ``limit=None`` returns every matching entry and is intended for exports.
    """
    if limit is not None and not 1 <= limit <= 200:
        raise ValueError("Entry limit must be between 1 and 200, or None.")
    where, parameters = _search_clause(query)
    sql = (
        "SELECT id, title, category, content, sanity, created_at, updated_at "
        f"FROM archive_entries{where} ORDER BY updated_at DESC, id DESC"
    )
    if limit is not None:
        sql += " LIMIT ?"
        parameters = (*parameters, limit)
    rows = get_db().execute(sql, parameters).fetchall()
    return [_entry_from_row(row) for row in rows]


def count_entries(query: str = "") -> int:
    """Return the total number of entries matching ``query``."""
    where, parameters = _search_clause(query)
    row = get_db().execute(
        f"SELECT COUNT(*) AS total FROM archive_entries{where}",
        parameters,
    ).fetchone()
    return int(row["total"])


def get_entry(entry_id: int) -> ArchiveEntry | None:
    row = get_db().execute(
        "SELECT id, title, category, content, sanity, created_at, updated_at "
        "FROM archive_entries WHERE id = ?",
        (entry_id,),
    ).fetchone()
    return _entry_from_row(row) if row is not None else None


def create_entry(title: str, category: str, content: str, sanity: int) -> int:
    now = _now()
    cursor = get_db().execute(
        "INSERT INTO archive_entries "
        "(title, category, content, sanity, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (title, category, content, sanity, now, now),
    )
    return int(cursor.lastrowid)


def update_entry(
    entry_id: int,
    title: str,
    category: str,
    content: str,
    sanity: int,
) -> bool:
    cursor = get_db().execute(
        "UPDATE archive_entries SET title = ?, category = ?, content = ?, "
        "sanity = ?, updated_at = ? WHERE id = ?",
        (title, category, content, sanity, _now(), entry_id),
    )
    return cursor.rowcount == 1


def delete_entry(entry_id: int) -> bool:
    cursor = get_db().execute(
        "DELETE FROM archive_entries WHERE id = ?",
        (entry_id,),
    )
    return cursor.rowcount == 1


def _entry_from_row(row: sqlite3.Row) -> ArchiveEntry:
    return ArchiveEntry(
        id=row["id"],
        title=row["title"],
        category=row["category"],
        content=row["content"],
        sanity=row["sanity"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _search_clause(query: str) -> tuple[str, tuple[Any, ...]]:
    if not query:
        return "", ()
    escaped = _escape_like(query)
    return (
        " WHERE title LIKE ? ESCAPE '\\' OR category LIKE ? ESCAPE '\\'",
        (f"%{escaped}%", f"%{escaped}%"),
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
