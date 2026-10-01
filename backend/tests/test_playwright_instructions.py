from app.drivers.playwright_instructions import is_template_playwright_notes


def test_template_playwright_notes_detects_examples():
    assert is_template_playwright_notes(
        "e.g. Click parcel search tab, fill owner field, wait for results table"
    )
    assert is_template_playwright_notes("Auto-scrape publicrecords.netronline.com for portal links.")
    assert is_template_playwright_notes("")


def test_template_playwright_notes_allows_real_instructions():
    assert not is_template_playwright_notes(
        "Click address search tab, fill address field, click search, wait for results table"
    )
