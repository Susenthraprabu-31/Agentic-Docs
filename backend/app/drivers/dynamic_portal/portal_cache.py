"""Portal Cache and Fingerprinting layer for fast deterministic replay and self-healing."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from app.drivers.dynamic_portal.schemas import (
    CompactBrowserState,
    PortalAnalysis,
    PortalFingerprint,
    PortalMapping,
)

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parents[3] / "local_storage" / "portal_cache"


class PortalCache:
    """Manages cached portal knowledge, fingerprints, and fast validation."""

    def __init__(self, cache_dir: Optional[Path] = None) -> None:
        self.cache_dir = cache_dir or CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_key(self, state: str, county: str, portal_type: str = "assessor") -> str:
        s = state.lower().strip()
        c = county.lower().strip().replace(" ", "_")
        p = portal_type.lower().strip()
        return f"{s}_{c}_{p}"

    @property
    def _block_cache_file(self) -> Path:
        return self.cache_dir / "hard_blocks.json"

    def get_cache_file(self, state: str, county: str, portal_type: str = "assessor") -> Path:
        return self.cache_dir / f"{self._cache_key(state, county, portal_type)}.json"

    @staticmethod
    def _domain_key(url: str) -> str:
        return urlparse(url).netloc.lower().removeprefix("www.")

    def get_active_hard_block(self, url: str, cooldown_minutes: int) -> Optional[Dict[str, Any]]:
        """Return a recent hard-denial record so callers can avoid re-hitting it."""
        domain = self._domain_key(url)
        if not domain or not self._block_cache_file.exists():
            return None
        try:
            entries = json.loads(self._block_cache_file.read_text(encoding="utf-8"))
            entry = entries.get(domain)
            blocked_at = datetime.fromisoformat(entry["blocked_at"])
            if blocked_at + timedelta(minutes=cooldown_minutes) > datetime.now(timezone.utc):
                return entry
        except Exception as exc:
            logger.debug("Failed to read hard-block cache: %s", exc)
        return None

    def record_hard_block(self, url: str, reason: str = "") -> None:
        """Persist only hard access denials; challenges and CAPTCHAs are not cached."""
        domain = self._domain_key(url)
        if not domain:
            return
        try:
            entries: Dict[str, Any] = {}
            if self._block_cache_file.exists():
                entries = json.loads(self._block_cache_file.read_text(encoding="utf-8"))
            entries[domain] = {
                "blocked_at": datetime.now(timezone.utc).isoformat(),
                "reason": reason or "Portal returned an access-denied page.",
            }
            self._block_cache_file.write_text(json.dumps(entries, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("Failed to record hard portal block: %s", exc)

    def clear_hard_block(self, url: str) -> None:
        """Clear a prior denial after the portal becomes usable again."""
        domain = self._domain_key(url)
        if not domain or not self._block_cache_file.exists():
            return
        try:
            entries = json.loads(self._block_cache_file.read_text(encoding="utf-8"))
            if domain in entries:
                del entries[domain]
                self._block_cache_file.write_text(json.dumps(entries, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.debug("Failed to clear hard-block cache: %s", exc)

    def compute_fingerprint(
        self,
        url: str,
        title: str,
        state: CompactBrowserState,
    ) -> PortalFingerprint:
        """Create lightweight fingerprint of search page structure without full HTML."""
        domain = urlparse(url).netloc.lower()
        path = urlparse(url).path.lower()

        # Build form signature from input tags, types, and names
        input_sigs = []
        for inp in sorted(state.inputs, key=lambda x: x.selector):
            input_sigs.append(f"{inp.tag}:{inp.type}:{inp.name or inp.id or inp.placeholder}")
        form_sig = ";".join(input_sigs[:15])

        stable_ids = [inp.id for inp in state.inputs if inp.id and not any(ch.isdigit() for ch in inp.id)]

        return PortalFingerprint(
            domain=domain,
            url_pattern=path,
            page_title_pattern=title[:60],
            form_signature=form_sig,
            stable_identifiers=stable_ids[:10],
        )

    def load_mapping(
        self, state: str, county: str, portal_type: str = "assessor"
    ) -> Optional[PortalMapping]:
        """Load cached mapping if present."""
        path = self.get_cache_file(state, county, portal_type)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return PortalMapping(**data)
        except Exception as exc:
            logger.warning("Failed to load cached mapping from %s: %s", path, exc)
            return None

    def save_mapping(
        self,
        state: str,
        county: str,
        mapping: PortalMapping,
    ) -> None:
        """Persist verified mapping to disk."""
        path = self.get_cache_file(state, county, mapping.portal_type)
        try:
            mapping.last_verified = datetime.now(timezone.utc).isoformat()
            path.write_text(json.dumps(mapping.model_dump(), indent=2), encoding="utf-8")
            logger.info("Saved portal mapping cache: %s", path.name)
        except Exception as exc:
            logger.warning("Failed to save portal mapping to %s: %s", path, exc)

    def invalidate(self, state: str, county: str, portal_type: str = "assessor") -> None:
        """Remove stale cached mapping."""
        path = self.get_cache_file(state, county, portal_type)
        if path.exists():
            try:
                path.unlink()
                logger.info("Invalidated stale portal cache: %s", path.name)
            except Exception as exc:
                logger.warning("Failed to invalidate cache %s: %s", path, exc)

    async def validate_cached_mapping(
        self,
        mapping: PortalMapping,
        page_or_frame: Any,
        current_state: CompactBrowserState,
    ) -> bool:
        """
        Validate whether the cached mapping is still operational on the current page.
        1. Checks domain match
        2. Validates that primary search field selectors exist, are visible, and enabled
        """
        try:
            # Check domain
            curr_domain = urlparse(current_state.url).netloc.lower()
            if mapping.domain and mapping.domain not in curr_domain and curr_domain not in mapping.domain:
                return False

            # Check at least one primary search field selector
            search_fields = mapping.search_fields
            if not search_fields:
                return False

            valid_count = 0
            for field_type, field_data in search_fields.items():
                selector = field_data.get("selector") if isinstance(field_data, dict) else getattr(field_data, "selector", None)
                if not selector:
                    continue

                loc = page_or_frame.locator(selector).first
                if await loc.count() > 0 and await loc.is_visible(timeout=2000):
                    valid_count += 1

            # If submit button selector exists in mapping, check it as well
            if mapping.submit_selector:
                btn_loc = page_or_frame.locator(mapping.submit_selector).first
                if await btn_loc.count() > 0:
                    valid_count += 1

            return valid_count >= 1

        except Exception as exc:
            logger.debug("Cached mapping validation check encountered error: %s", exc)
            return False
