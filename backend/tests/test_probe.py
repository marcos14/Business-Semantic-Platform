"""Sonda de franquia: chamada mínima ao harness para saber se os créditos voltaram."""

import sys
from pathlib import Path

from app.engines import claude_code

FAKE = [sys.executable, str(Path(__file__).parent / "fake_claude.py")]


def test_probe_detecta_limite(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_SCENARIO", "limit")
    res = claude_code.probe(tmp_path / "logs", executable=FAKE)
    assert res.session_limit and res.is_error


def test_probe_detecta_deslogado(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_SCENARIO", "auth")
    res = claude_code.probe(tmp_path / "logs", executable=FAKE)
    assert res.auth_failed


def test_probe_ok_quando_ha_credito(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_SCENARIO", "discovery_ok")
    res = claude_code.probe(tmp_path / "logs", executable=FAKE)
    assert not res.is_error and not res.session_limit and not res.auth_failed
    assert Path(res.log_path).name.startswith("probe-franquia-")
