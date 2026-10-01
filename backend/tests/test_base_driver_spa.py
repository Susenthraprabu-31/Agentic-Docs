from app.drivers.base.base_driver import spa_navigation_profile


def test_spa_navigation_profile_miami_dade():
    profile = spa_navigation_profile("https://apps.miamidadepa.gov/propertysearch/#/")
    assert profile is not None
    assert "mat-tab-group" in str(profile["wait_selector"])


def test_spa_navigation_profile_miami_dade_legacy_host():
    profile = spa_navigation_profile("https://apps.miamidade.gov/propertysearch/#/")
    assert profile is not None
    assert "mat-tab-group" in str(profile["wait_selector"])


def test_spa_navigation_profile_miami_dade_clerk():
    profile = spa_navigation_profile(
        "https://onlineservices.miamidadeclerk.gov/officialrecords"
    )
    assert profile is not None
    assert "bookType" in str(profile["wait_selector"])


def test_spa_navigation_profile_non_spa():
    assert spa_navigation_profile("https://www.netronline.com/") is None


def test_spa_navigation_profile_schneider():
    profile = spa_navigation_profile(
        "https://qpublic.schneidercorp.com/Application.aspx?AppID=1081&PageTypeID=2"
    )
    assert profile is not None
    assert "ctlBodyPane" in str(profile["wait_selector"])
