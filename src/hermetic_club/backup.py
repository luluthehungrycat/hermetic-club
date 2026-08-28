"""Safe SQLite backup and integrity-check helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path

_SQLITE_PREFIX = "sqlite+aiosqlite:///"


def sqlite_path(database_url: str) -> Path:
    """Return the filesystem path from a supported SQLite database URL."""
    if not database_url.startswith(_SQLITE_PREFIX):
        raise ValueError("backup currently supports sqlite+aiosqlite URLs only")
    return Path(database_url.removeprefix(_SQLITE_PREFIX)).expanduser()


def backup_database(database_url: str, destination: str | Path) -> Path:
    """Create a consistent SQLite backup using SQLite's online backup API."""
    source = sqlite_path(database_url)
    if not source.is_file():
        raise FileNotFoundError(source)
    target = Path(destination).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.resolve() == source.resolve():
        raise ValueError("backup destination must differ from the live database")

    source_connection = sqlite3.connect(source)
    target_connection = sqlite3.connect(target)
    try:
        source_connection.backup(target_connection)
        target_connection.commit()
    finally:
        target_connection.close()
        source_connection.close()
    return target


def check_database(path: str | Path) -> bool:
    """Run SQLite's integrity check and return whether it reports ``ok``."""
    connection = sqlite3.connect(Path(path).expanduser())
    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()
    finally:
        connection.close()
    return bool(result and result[0] == "ok")
