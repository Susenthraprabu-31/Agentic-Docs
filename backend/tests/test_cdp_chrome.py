from app.drivers.cdp_chrome import (
    _cdp_version_url,
    default_cdp_profile_dir,
    is_cdp_chrome_running,
)


def test_cdp_version_url():
    assert _cdp_version_url("http://127.0.0.1:9222") == "http://127.0.0.1:9222/json/version"


def test_default_profile_dir():
    assert default_cdp_profile_dir().name == "DonoChromeProfile"


def test_is_cdp_chrome_running_false_when_down():
    assert is_cdp_chrome_running("http://127.0.0.1:59999") is False
