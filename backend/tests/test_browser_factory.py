"""Tests for centralized browser factory helpers."""

from pathlib import Path

import pytest

from app.drivers.browser_factory import (
    USER_AGENTS,
    build_proxy_config,
    is_cloudflare_challenge_title,
    pick_user_agent,
    resolve_profile_path,
)


def test_pick_user_agent_returns_known_value():
    assert pick_user_agent() in USER_AGENTS


def test_is_cloudflare_challenge_title():
    assert is_cloudflare_challenge_title("Just a moment...")
    assert is_cloudflare_challenge_title("Attention Required | example.com")
    assert not is_cloudflare_challenge_title("Baker County Property Appraiser")


def test_resolve_profile_path_clean_when_chrome_profile_unset(monkeypatch, tmp_path):
    from app.config.settings import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("USE_CHROME_PROFILE", "true")
    monkeypatch.setenv("CHROME_USER_DATA_DIR", "")
    monkeypatch.setenv("PLAYWRIGHT_USER_DATA_DIR", str(tmp_path / "automation"))

    assert resolve_profile_path(use_persistent_profile=True) is None

    get_settings.cache_clear()


def test_resolve_profile_path_uses_chrome_dir(monkeypatch, tmp_path):
    from app.config.settings import get_settings

    chrome_dir = tmp_path / "chrome-profile"
    get_settings.cache_clear()
    monkeypatch.setenv("USE_CHROME_PROFILE", "true")
    monkeypatch.setenv("CHROME_USER_DATA_DIR", str(chrome_dir))

    profile = resolve_profile_path(use_persistent_profile=False)
    assert profile == chrome_dir
    assert profile.exists()

    get_settings.cache_clear()


def test_resolve_profile_path_playwright_fallback(monkeypatch, tmp_path):
    from app.config.settings import get_settings

    automation_dir = tmp_path / "automation-profile"
    get_settings.cache_clear()
    monkeypatch.setenv("USE_CHROME_PROFILE", "false")
    monkeypatch.setenv("PLAYWRIGHT_USER_DATA_DIR", str(automation_dir))

    profile = resolve_profile_path(use_persistent_profile=True)
    assert profile == automation_dir
    assert profile.exists()

    get_settings.cache_clear()


def test_build_proxy_config_disabled(monkeypatch):
    from app.config.settings import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("USE_PROXY", "false")
    monkeypatch.setenv("PROXY_URL", "http://user:pass@host:port")

    assert build_proxy_config() is None

    get_settings.cache_clear()


def test_build_proxy_config_enabled(monkeypatch):
    from app.config.settings import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("USE_PROXY", "true")
    monkeypatch.setenv("PROXY_URL", "http://user:pass@host:port")

    assert build_proxy_config() == {"server": "http://user:pass@host:port"}

    get_settings.cache_clear()
