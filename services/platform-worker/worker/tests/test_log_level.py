from worker.main import resolve_log_level
import logging


def test_default_is_info(monkeypatch):
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    assert resolve_log_level() == logging.INFO


def test_debug_from_env(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    assert resolve_log_level() == logging.DEBUG


def test_case_insensitive(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "debug")
    assert resolve_log_level() == logging.DEBUG


def test_invalid_falls_back_to_info(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "BOGUS")
    assert resolve_log_level() == logging.INFO
