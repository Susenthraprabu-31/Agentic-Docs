"""Browser-side scraping helpers for Miami-Dade recorder party names."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.extraction.miami_dade_name_searches import (
    collect_party_names_from_metadata,
    dedupe_party_names,
)

if TYPE_CHECKING:
    from app.drivers.base.base_driver import BaseDriver

logger = logging.getLogger(__name__)

_SCRAPE_RECORD_PARTY_NAMES_JS = """
() => {
  const names = [];
  const seen = new Set();
  const add = (raw) => {
    if (!raw) return;
    String(raw)
      .split(/[,/\\n;]+/)
      .forEach((part) => {
        let name = part.trim().replace(/\\s+ET\\s+AL\\.?$/i, '').trim();
        if (!name) return;
        if (/^(party name|party type|direct|reverse|parties)$/i.test(name)) return;
        const key = name.toUpperCase();
        if (seen.has(key)) return;
        seen.add(key);
        names.push(key);
      });
  };

  for (const table of document.querySelectorAll('table')) {
    const rows = [...table.querySelectorAll('tr')];
    if (!rows.length) continue;
    const header = (rows[0].innerText || '').toLowerCase();
    if (!header.includes('party name')) continue;
    for (const row of rows.slice(1)) {
      const cells = [...row.querySelectorAll('th, td')].map((c) => (c.innerText || '').trim());
      if (cells.length >= 2 && /^(direct|reverse)$/i.test(cells[1])) {
        add(cells[0]);
      } else if (cells.length >= 1) {
        add(cells[0]);
      }
    }
  }

  const text = document.body?.innerText || '';
  const lines = text.split('\\n').map((l) => l.trim()).filter(Boolean);
  for (let i = 0; i < lines.length; i++) {
    if (/^(direct|reverse)$/i.test(lines[i]) && i > 0) {
      add(lines[i - 1]);
    }
  }

  return names;
}
"""

_SCRAPE_SEARCH_RESULTS_PARTY_NAMES_JS = """
() => {
  const names = [];
  const seen = new Set();
  const add = (raw) => {
    if (!raw) return;
    String(raw)
      .split(/[,/\\n;]+/)
      .forEach((part) => {
        let name = part.trim().replace(/\\s+ET\\s+AL\\.?$/i, '').trim();
        if (!name) return;
        const key = name.toUpperCase();
        if (seen.has(key)) return;
        seen.add(key);
        names.push(key);
      });
  };

  const cards = [...document.querySelectorAll('.TitleSearchTab')];
  for (const card of cards) {
    const text = card.innerText || '';
    const partyMatch = text.match(/Party Name\\s*:?\\s*\\n([^\\n]+)/i);
    if (partyMatch && partyMatch[1]) add(partyMatch[1]);
  }
  return names;
}
"""


async def scrape_miami_dade_record_party_names(driver: "BaseDriver") -> list[str]:
    """Read all party names from a Miami-Dade recordpage CFN Details view."""
    try:
        raw_names = await driver.page.evaluate(_SCRAPE_RECORD_PARTY_NAMES_JS)
        if isinstance(raw_names, list):
            return dedupe_party_names([str(name) for name in raw_names])
    except Exception as exc:
        logger.debug("Could not scrape Miami-Dade record party names: %s", exc)
    return []


async def scrape_miami_dade_search_results_party_names(driver: "BaseDriver") -> list[str]:
    """Read party names shown on a Miami-Dade search results page."""
    try:
        raw_names = await driver.page.evaluate(_SCRAPE_SEARCH_RESULTS_PARTY_NAMES_JS)
        if isinstance(raw_names, list):
            return dedupe_party_names([str(name) for name in raw_names])
    except Exception as exc:
        logger.debug("Could not scrape Miami-Dade search-result party names: %s", exc)
    return []


async def collect_miami_dade_party_names_for_document(
    driver: "BaseDriver",
    metadata: dict[str, Any],
    *,
    include_search_results: bool = False,
) -> list[str]:
    """Merge party names from metadata and the active recorder page."""
    names = collect_party_names_from_metadata(metadata)
    if "recordpage" in driver.page.url.lower():
        names.extend(await scrape_miami_dade_record_party_names(driver))
    elif include_search_results and "searchresults" in driver.page.url.lower():
        names.extend(await scrape_miami_dade_search_results_party_names(driver))
    return dedupe_party_names(names)


def apply_party_names_to_recorded_document(doc: Any, party_names: list[str]) -> Any:
    """Attach extracted party names to a RecordedDocument without altering other fields."""
    if not party_names:
        return doc
    ocr_json = dict(getattr(doc, "ocr_json", None) or {})
    ocr_json["party_names"] = party_names
    ocr_json["name_search_names"] = party_names
    doc.ocr_json = ocr_json
    return doc
