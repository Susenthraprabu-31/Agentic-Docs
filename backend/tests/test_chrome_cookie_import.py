from app.drivers.chrome_cookie_import import _to_playwright_cookie, portal_domains_for_url


class _FakeCookie:
    name = "cf_clearance"
    value = "abc123"
    domain = ".schneidercorp.com"
    path = "/"
    expires = 9999999999
    secure = True
    _rest = {"HttpOnly": True}


def test_to_playwright_cookie():
    pw = _to_playwright_cookie(_FakeCookie())
    assert pw["name"] == "cf_clearance"
    assert pw["domain"] == ".schneidercorp.com"
    assert pw["httpOnly"] is True


def test_portal_domains_for_schneider_url():
    domains = portal_domains_for_url(
        "https://qpublic.schneidercorp.com/Application.aspx?AppID=1081"
    )
    assert "schneidercorp.com" in domains
