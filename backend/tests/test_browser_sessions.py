from app.drivers.browser_sessions import portal_session_key, session_file_for


def test_portal_session_key():
    url = "https://qpublic.schneidercorp.com/Application.aspx?AppID=1081"
    assert portal_session_key(url) == "qpublic.schneidercorp.com"
    assert session_file_for(url).name == "qpublic.schneidercorp.com.json"
