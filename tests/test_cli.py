"""CLI initialization safety tests."""

from hermetic_club.cli import _ensure_config


def test_ensure_config_preserves_existing_user_config(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    config_dir = tmp_path / ".hermetic-club"
    config_dir.mkdir()
    config_path = config_dir / "config.yaml"
    original = "host: 0.0.0.0\nport: 9443\nsecret_key: user-secret\n"
    config_path.write_text(original, encoding="utf-8")

    _ensure_config()

    assert config_path.read_text(encoding="utf-8") == original
    assert "Config already exists" in capsys.readouterr().out


def test_ensure_config_creates_missing_config(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))

    _ensure_config()

    config_path = tmp_path / ".hermetic-club" / "config.yaml"
    assert config_path.is_file()
    assert "Hermetic Club Configuration" in config_path.read_text(encoding="utf-8")
