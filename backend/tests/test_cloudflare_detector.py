import pytest
from datetime import datetime, timezone

from app.drivers.dynamic_portal.cloudflare_detector import CloudflareDetector
from app.drivers.dynamic_portal.schemas import BlockingType, RunErrorStatus
from app.drivers.dynamic_portal.portal_cache import PortalCache


@pytest.mark.parametrize(
    ("blocking_type", "expected_status"),
    [
        (BlockingType.CLOUDFLARE_CHALLENGE, RunErrorStatus.CLOUDFLARE_CHALLENGE),
        (BlockingType.CAPTCHA, RunErrorStatus.CAPTCHA_DETECTED),
        (BlockingType.ACCESS_DENIED, RunErrorStatus.ACCESS_DENIED),
        (BlockingType.RATE_LIMITED, RunErrorStatus.RATE_LIMITED),
        (BlockingType.LOGIN_REQUIRED, RunErrorStatus.LOGIN_REQUIRED),
        (BlockingType.NETWORK_ERROR, RunErrorStatus.NETWORK_ERROR),
    ],
)
def test_blocking_types_keep_their_specific_run_status(blocking_type, expected_status):
    assert CloudflareDetector.to_run_error_status(blocking_type) == expected_status


def test_screenshot_hard_block_is_classified_as_access_denied_without_retry():
    result = CloudflareDetector().detect_blocking(
        url="https://beacon.schneidercorp.com/Application.aspx",
        title="Attention Required! | Cloudflare",
        visible_text="Sorry, you have been blocked. You are unable to access schneidercorp.com.",
        status_code=403,
    )

    assert result.type == BlockingType.ACCESS_DENIED
    assert result.recommendedAction == "MANUAL_REVIEW_REQUIRED"
    assert CloudflareDetector().should_retry_network(1, result.type) is False


def test_hard_block_cache_quarantines_a_domain(tmp_path):
    cache = PortalCache(cache_dir=tmp_path)
    cache.record_hard_block("https://beacon.schneidercorp.com/Application.aspx", "blocked")

    blocked = cache.get_active_hard_block("https://beacon.schneidercorp.com/other", 60)

    assert blocked is not None
    assert blocked["reason"] == "blocked"
