"""Safe SQLite backup and integrity-check helpers."""

from __future__ import annotations

import os
import sqlite3
import tempfile
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

    fd, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    source_connection = sqlite3.connect(source)
    target_connection = sqlite3.connect(temporary)
    try:
        source_connection.backup(target_connection)
        target_connection.commit()
        os.replace(temporary, target)
        directory_fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        target_connection.close()
        source_connection.close()
        temporary.unlink(missing_ok=True)
    return target


def check_database(path: str | Path) -> bool:
    """Run SQLite's integrity check and return whether it reports ``ok``."""
    database = Path(path).expanduser()
    if not database.is_file():
        raise FileNotFoundError(database)
    connection = sqlite3.connect(database)
    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()
    finally:
        connection.close()
    return bool(result and result[0] == "ok")
