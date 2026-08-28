"""Tests for SQLite backup and integrity-check helpers."""

import sqlite3

import pytest

from hermetic_club.backup import backup_database, check_database, sqlite_path


def test_sqlite_path_rejects_non_sqlite_urls():
    with pytest.raises(ValueError):
        sqlite_path("postgresql://example/database")


def test_backup_uses_online_backup_and_passes_integrity_check(tmp_path):
    source = tmp_path / "club.db"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE facts (value TEXT NOT NULL)")
        connection.execute("INSERT INTO facts VALUES (?)", ("preserved",))

    destination = backup_database(f"sqlite+aiosqlite:///{source}", tmp_path / "backup.db")

    assert destination.is_file()
    assert check_database(destination)
    with sqlite3.connect(destination) as connection:
        assert connection.execute("SELECT value FROM facts").fetchone() == ("preserved",)


def test_backup_rejects_live_database_as_destination(tmp_path):
    source = tmp_path / "club.db"
    source.touch()

    with pytest.raises(ValueError):
        backup_database(f"sqlite+aiosqlite:///{source}", source)


def test_check_database_rejects_missing_file_without_creating_it(tmp_path):
    missing = tmp_path / "missing.db"

    with pytest.raises(FileNotFoundError):
        check_database(missing)

    assert not missing.exists()
