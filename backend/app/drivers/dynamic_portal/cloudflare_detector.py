"""Cloudflare and Anti-Bot Blocking Detector with safe recovery policies."""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from app.drivers.dynamic_portal.schemas import BlockingType, DetectionResult, RunErrorStatus

logger = logging.getLogger(__name__)


# Specific signal patterns for detection
CLOUDFLARE_TITLE_PATTERNS = [
    r"just a moment",
    r"attention required",
    r"cloudflare",
    r"security check",
    r"ddos-guard",
]

CLOUDFLARE_BODY_MARKERS = [
    "checking your browser",
    "performing security verification",
    "verify you are human",
    "cf-browser-verification",
    "challenge-platform",
    "turnstile",
    "cf_chl_opt",
    "ray id:",
    "security service to protect against malicious bots",
    "enable javascript and cookies to continue",
]

CAPTCHA_MARKERS = [
    "g-recaptcha",
    "recaptcha",
    "hcaptcha",
    "arkoselabs",
    "funcaptcha",
    "enter the characters you see",
    "security captcha",
    "please solve this puzzle",
]

ACCESS_DENIED_MARKERS = [
    "access denied",
    "403 forbidden",
    "you do not have permission to access",
    "you have been blocked",
    "sorry, you have been blocked",
    "error 1020",
    "error 1006",
    "error 1015",
    "your ip has been banned",
]

RATE_LIMIT_MARKERS = [
    "too many requests",
    "429 too many requests",
    "rate limit exceeded",
    "request rate exceeded",
    "please wait a few minutes before trying again",
    "slow down",
]

LOGIN_REQUIRED_MARKERS = [
    "please log in to continue",
    "login required",
    "sign in to your account",
    "subscriber access only",
    "authentication required",
]


class CloudflareDetector:
    """Multi-signal blocking and challenge detector."""

    def __init__(self, max_transient_retries: int = 2) -> None:
        self.max_transient_retries = max_transient_retries

    def detect_blocking(
        self,
        url: str,
        title: str = "",
        visible_text: str = "",
        status_code: Optional[int] = None,
        html_content: str = "",
        has_actionable_content: bool = False,
    ) -> DetectionResult:
        """
        Analyze current page metadata, title, text, and response code to classify blocking.
        Does not depend on any single string; evaluates weighted signals.
        """
        lower_title = (title or "").lower().strip()
        lower_text = (visible_text or "").lower()
        lower_html = (html_content or "").lower()
        lower_url = (url or "").lower()

        # If standard page elements are clearly functional and loaded, avoid false positives
        if has_actionable_content and not any(m in lower_title for m in ["just a moment", "attention required"]):
            return DetectionResult(
                blocked=False,
                type=BlockingType.NORMAL,
                confidence=0.98,
                recommendedAction="CONTINUE",
                details={"has_actionable_content": True},
            )

        # 1. Rate Limiting Check (HTTP 429 or explicit rate limit markers)
        if status_code == 429 or any(marker in lower_text or marker in lower_title for marker in RATE_LIMIT_MARKERS):
            return DetectionResult(
                blocked=True,
                type=BlockingType.RATE_LIMITED,
                confidence=0.98 if status_code == 429 else 0.90,
                recommendedAction="STOP_IMMEDIATELY",
                details={
                    "status_code": status_code,
                    "reason": "Server rate limit hit. Do not retry aggressively.",
                },
            )

        # 2. Access Denied / Hard Block (HTTP 403 or explicit ban markers)
        if status_code in (401, 403) and any(m in lower_text or m in lower_html for m in ACCESS_DENIED_MARKERS):
            return DetectionResult(
                blocked=True,
                type=BlockingType.ACCESS_DENIED,
                confidence=0.96,
                recommendedAction="MANUAL_REVIEW_REQUIRED",
                details={
                    "status_code": status_code,
                    "reason": "Direct access denied or permanent IP block.",
                },
            )

        # 3. Cloudflare Interstitial / Challenge Check
        cf_title_match = any(re.search(pat, lower_title) for pat in CLOUDFLARE_TITLE_PATTERNS)
        cf_body_matches = sum(1 for m in CLOUDFLARE_BODY_MARKERS if m in lower_text or m in lower_html)

        if cf_title_match or cf_body_matches >= 2:
            confidence = min(0.99, 0.70 + (0.15 if cf_title_match else 0.0) + (cf_body_matches * 0.08))
            return DetectionResult(
                blocked=True,
                type=BlockingType.CLOUDFLARE_CHALLENGE,
                confidence=round(confidence, 2),
                recommendedAction="STOP_AND_RECOVER",
                details={
                    "title_match": cf_title_match,
                    "body_signals": cf_body_matches,
                    "page_title": title,
                },
            )

        # 4. CAPTCHA Check (Google reCAPTCHA, hCaptcha, Arkose)
        captcha_matches = sum(1 for m in CAPTCHA_MARKERS if m in lower_text or m in lower_html)
        if captcha_matches >= 1 and ("captcha" in lower_title or "challenge" in lower_text or captcha_matches >= 2):
            return DetectionResult(
                blocked=True,
                type=BlockingType.CAPTCHA,
                confidence=0.95,
                recommendedAction="MANUAL_REVIEW_REQUIRED",
                details={
                    "captcha_signals": captcha_matches,
                    "reason": "Interactive CAPTCHA encountered.",
                },
            )

        # 5. Login / Subscription Requirement
        if any(marker in lower_text or marker in lower_title for marker in LOGIN_REQUIRED_MARKERS):
            # Check if this isn't just a small navbar "login" link
            if len(lower_text) < 600 or "login" in lower_title or "sign in" in lower_title:
                return DetectionResult(
                    blocked=True,
                    type=BlockingType.LOGIN_REQUIRED,
                    confidence=0.88,
                    recommendedAction="MANUAL_REVIEW_REQUIRED",
                    details={"reason": "County portal requires credentials or account subscription."},
                )

        # 6. HTTP 5xx Server / Gateway Errors
        if status_code and 500 <= status_code <= 599:
            return DetectionResult(
                blocked=True,
                type=BlockingType.NETWORK_ERROR,
                confidence=0.95,
                recommendedAction="RETRY_TRANSIENT",
                details={"status_code": status_code, "reason": "Server returned gateway/internal error"},
            )

        # 7. Access Denied without 403 (e.g. 200 OK with "Access Denied" page)
        if any(marker in lower_text for marker in ACCESS_DENIED_MARKERS) and len(lower_text) < 800:
            return DetectionResult(
                blocked=True,
                type=BlockingType.ACCESS_DENIED,
                confidence=0.85,
                recommendedAction="MANUAL_REVIEW_REQUIRED",
                details={"reason": "Access denied message in short page body."},
            )

        # Default: Normal page
        return DetectionResult(
            blocked=False,
            type=BlockingType.NORMAL,
            confidence=0.95,
            recommendedAction="CONTINUE",
        )

    def should_retry_network(self, attempt_count: int, error_type: BlockingType) -> bool:
        """
        Bounded retry policy for transient errors ONLY.
        Never retry aggressively when Cloudflare, CAPTCHA, or Rate Limiting is detected.
        """
        if error_type in (
            BlockingType.CLOUDFLARE_CHALLENGE,
            BlockingType.CAPTCHA,
            BlockingType.ACCESS_DENIED,
            BlockingType.RATE_LIMITED,
            BlockingType.LOGIN_REQUIRED,
        ):
            return False

        if error_type == BlockingType.NETWORK_ERROR and attempt_count <= self.max_transient_retries:
            return True

        return False

    @staticmethod
    def to_run_error_status(blocking_type: BlockingType) -> RunErrorStatus:
        """Translate a portal security outcome into the API's precise run status.

        Keeping this mapping in one place prevents a new county driver from
        accidentally treating a CAPTCHA, rate limit, or hard denial as a
        generic Cloudflare error (or retrying it).
        """
        statuses = {
            BlockingType.CLOUDFLARE_CHALLENGE: RunErrorStatus.CLOUDFLARE_CHALLENGE,
            BlockingType.CAPTCHA: RunErrorStatus.CAPTCHA_DETECTED,
            BlockingType.ACCESS_DENIED: RunErrorStatus.ACCESS_DENIED,
            BlockingType.RATE_LIMITED: RunErrorStatus.RATE_LIMITED,
            BlockingType.LOGIN_REQUIRED: RunErrorStatus.LOGIN_REQUIRED,
            BlockingType.NETWORK_ERROR: RunErrorStatus.NETWORK_ERROR,
        }
        return statuses.get(blocking_type, RunErrorStatus.MANUAL_REVIEW_REQUIRED)
