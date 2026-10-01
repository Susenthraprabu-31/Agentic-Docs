"""Schneider Corp / qPublic / Beacon portal URL helpers — works for any US county."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

SCHNEIDER_HOSTS = ("schneidercorp.com", "qpublic.net")
SCHNEIDER_WARMUP_URL = "https://qpublic.schneidercorp.com/#search"
HONOLULU_WARMUP_URL = "https://www.qpublic.net/hi/honolulu/"

# qPublic global landing — single field for name, address, or parcel ID
QPUBLIC_GLOBAL_INPUT_SELECTORS: tuple[str, ...] = (
    'input[placeholder*="Search by name" i]',
    'input[placeholder*="parcel ID" i]',
    'input[placeholder*="address" i]',
    'input[aria-label*="search" i]',
    'input[type="search"]',
    "#searchInput",
    ".search-input input",
    'input[type="text"]',
)

QPUBLIC_GLOBAL_SEARCH_BUTTON_SELECTORS: tuple[str, ...] = (
    'button:has-text("Search")',
    'a:has-text("Search")',
    '[role="button"]:has-text("Search")',
    'button[aria-label*="Search" i]',
    'input[type="submit"][value*="Search" i]',
    '.search-button',
    '[class*="search"] button',
)

# Playwright page.evaluate — find the hero search input (works when CSS selectors miss SPA markup).
QPUBLIC_GLOBAL_FILL_JS = """
(val) => {
  const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
  const want = norm(val);
  const inputs = Array.from(document.querySelectorAll('input')).filter((el) => {
    if (el.type === 'hidden' || el.disabled) return false;
    const r = el.getBoundingClientRect();
    if (r.width < 80 || r.height < 10) return false;
    const st = getComputedStyle(el);
    return st.display !== 'none' && st.visibility !== 'hidden' && Number(st.opacity) > 0;
  });
  const ranked = inputs
    .map((el) => {
      const ph = norm(el.placeholder || el.getAttribute('aria-label') || '');
      let score = 0;
      if (ph.includes('search by name') || ph.includes('parcel')) score += 20;
      if (ph.includes('address')) score += 8;
      if (el.type === 'search') score += 5;
      score += Math.min(el.getBoundingClientRect().width / 40, 8);
      return { el, score };
    })
    .sort((a, b) => b.score - a.score);
  const el = ranked[0]?.el;
  if (!el) return { ok: false, reason: 'no-input' };
  el.scrollIntoView({ block: 'center' });
  el.focus();
  el.click();
  el.value = '';
  el.value = val;
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
  el.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
  const got = (el.value || '').replace(/\\s/g, '');
  const need = (val || '').replace(/\\s/g, '');
  return { ok: got.includes(need) || need.includes(got), value: el.value };
}
"""

QPUBLIC_GLOBAL_CLICK_SEARCH_JS = """
() => {
  const nodes = Array.from(
    document.querySelectorAll('button, a, [role="button"], input[type="submit"], span')
  );
  for (const el of nodes) {
    const label = (el.innerText || el.value || el.getAttribute('aria-label') || '')
      .replace(/\\s+/g, ' ')
      .trim()
      .toLowerCase();
    if (label === 'search' || label.startsWith('search ')) {
      const r = el.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) {
        el.click();
        return true;
      }
    }
  }
  const iconBtn = document.querySelector('[class*="search"] button, button[class*="search"]');
  if (iconBtn) {
    iconBtn.click();
    return true;
  }
  return false;
}
"""

HONOLULU_MARKERS = (
    "honolulucountyhi",
    "qpublic.net/hi/honolulu",
)

# App-name style: App=BayCountyFL
FL_SCHNEIDER_APP_PATTERN = re.compile(r"app=([a-z]+countyfl)", re.I)


def is_schneider_portal(url: str) -> bool:
    lower = (url or "").lower()
    return any(host in lower for host in SCHNEIDER_HOSTS)


def is_honolulu_schneider(url: str) -> bool:
    lower = (url or "").lower()
    return any(marker in lower for marker in HONOLULU_MARKERS)


def is_florida_schneider_portal(url: str) -> bool:
    """Any Schneider portal that is not Honolulu (used when state is FL)."""
    return is_schneider_portal(url) and not is_honolulu_schneider(url)


def is_schneider_search_url(url: str) -> bool:
    """True when the URL already targets a property search page."""
    lower = (url or "").lower()
    if "pagetype=search" in lower:
        return True
    # AppID / Beacon portals use PageTypeID=2 for property search (e.g. Alachua FL).
    if "pagetypeid=2" in lower and "application.aspx" in lower:
        return True
    return False


def _flatten_query(query: str) -> dict[str, str]:
    parsed = parse_qs(query, keep_blank_values=True)
    flat: dict[str, str] = {}
    for key, values in parsed.items():
        if values:
            flat[key] = values[0]
    return flat


def _preserve_param_case(original: dict[str, str], updates: dict[str, str]) -> dict[str, str]:
    """Apply updates while keeping original ASP.NET parameter casing when possible."""
    lower_to_key = {k.lower(): k for k in original}
    merged = dict(original)
    for key, value in updates.items():
        existing = lower_to_key.get(key.lower())
        if existing:
            merged[existing] = value
        else:
            merged[key] = value
    for remove_key in ("KeyValue", "Q", "keyvalue", "q"):
        merged.pop(remove_key, None)
        existing = lower_to_key.get(remove_key.lower())
        if existing:
            merged.pop(existing, None)
    return merged


def _build_url(url: str, params: dict[str, str]) -> str:
    parsed = urlparse(url)
    return urlunparse(parsed._replace(query=urlencode(params)))


def normalize_schneider_search_url(url: str) -> str:
    """Rewrite Schneider landing, map, or report URLs to a property search page.

    Handles both URL styles used across counties:
    - App=CountyFL&PageType=Search (e.g. Bay County FL)
    - AppID=1081&PageTypeID=2&PageID=... (e.g. Alachua County FL)
    """
    if not url or not is_schneider_portal(url):
        return url

    if is_schneider_search_url(url):
        flat = _flatten_query(urlparse(url).query)
        return _build_url(url, _preserve_param_case(flat, {}))

    parsed = urlparse(url)
    flat = _flatten_query(parsed.query)
    lower_keys = {k.lower(): v for k, v in flat.items()}

    app_name = lower_keys.get("app")
    if app_name and "appid" not in lower_keys:
        updated = _preserve_param_case(flat, {"PageType": "Search"})
        updated.pop("PageTypeID", None)
        for key in list(updated):
            if key.lower() == "pagetypeid":
                updated.pop(key, None)
        return _build_url(url, updated)

    app_id = lower_keys.get("appid")
    if app_id:
        page_type_id = lower_keys.get("pagetypeid", "")
        updates: dict[str, str] = {}
        if page_type_id == "4" or not page_type_id:
            updates["PageTypeID"] = "2"
            # Report PageID values differ from search PageID — drop when converting.
            if page_type_id == "4":
                for key in list(flat):
                    if key.lower() == "pageid":
                        flat.pop(key, None)
        updated = _preserve_param_case(flat, updates)
        return _build_url(url, updated)

    sep = "&" if parsed.query else "?"
    return f"{url}{sep}PageType=Search"


def is_qpublic_global_landing_url(url: str) -> bool:
    """qPublic homepage with unified name/address/parcel search (not county Application.aspx)."""
    lower = (url or "").lower()
    if not is_schneider_portal(url):
        return False
    if "application.aspx" in lower and is_schneider_search_url(url):
        return False
    if "application.aspx" in lower and "appid=" in lower:
        return False
    return (
        "#search" in lower
        or lower.rstrip("/").endswith("schneidercorp.com")
        or lower.rstrip("/").endswith("qpublic.net")
    )


def schneider_warmup_url(url: str) -> str | None:
    """Landing page to visit before deep-linking — reduces Cloudflare bot flags.

    County-specific Application.aspx search URLs (AppID=… or App=…&PageType=Search)
    should be opened directly — global warmup often triggers extra Cloudflare checks.
    """
    if not is_schneider_portal(url):
        return None
    if is_schneider_search_url(url):
        return None
    if is_honolulu_schneider(url):
        return HONOLULU_WARMUP_URL
    return SCHNEIDER_WARMUP_URL


def schneider_portal_key(url: str) -> str | None:
    """Stable identity for a county portal (AppID or App name)."""
    if not url:
        return None
    flat = _flatten_query(urlparse(url).query)
    lower = {k.lower(): v for k, v in flat.items()}
    if lower.get("appid"):
        return f"appid:{lower['appid']}"
    if lower.get("app"):
        return f"app:{lower['app'].lower()}"
    return None


def is_same_schneider_portal(current_url: str, target_url: str) -> bool:
    """True when both URLs refer to the same county Schneider portal."""
    current_key = schneider_portal_key(current_url)
    target_key = schneider_portal_key(target_url)
    if current_key and target_key:
        return current_key == target_key
    return False


def should_use_global_qpublic_search(url: str) -> bool:
    """Global hero search is only for generic qPublic landing URLs."""
    if not is_schneider_portal(url):
        return False
    if is_schneider_search_url(url):
        return False
    if "application.aspx" in (url or "").lower():
        return False
    return True


def get_schneider_county_slug(url: str) -> str | None:
    """Best-effort county slug from a Schneider URL."""
    lower = (url or "").lower()
    match = FL_SCHNEIDER_APP_PATTERN.search(lower)
    if match:
        return match.group(1).replace("countyfl", "").replace("county", "")
    if is_schneider_portal(url) and not is_honolulu_schneider(url):
        return "schneider"
    return None
