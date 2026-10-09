from app.config.settings import get_settings
from app.drivers.recorder.miami_dade_clerk_login import miami_dade_clerk_credentials_configured


def test_miami_dade_clerk_credentials_configured_requires_username_and_password():
    settings = get_settings()
    original_user = settings.miami_dade_clerk_username
    original_pass = settings.miami_dade_clerk_password
    original_auto = settings.miami_dade_clerk_auto_login

    settings.miami_dade_clerk_username = ""
    settings.miami_dade_clerk_password = ""
    settings.miami_dade_clerk_auto_login = True
    assert miami_dade_clerk_credentials_configured() is False

    settings.miami_dade_clerk_username = "user@example.com"
    settings.miami_dade_clerk_password = "secret"
    settings.miami_dade_clerk_auto_login = True
    assert miami_dade_clerk_credentials_configured() is True

    settings.miami_dade_clerk_auto_login = False
    assert miami_dade_clerk_credentials_configured() is False

    settings.miami_dade_clerk_username = original_user
    settings.miami_dade_clerk_password = original_pass
    settings.miami_dade_clerk_auto_login = original_auto
