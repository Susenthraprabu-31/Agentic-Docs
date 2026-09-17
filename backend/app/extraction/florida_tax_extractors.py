"""Extractors for Florida county tax collector sites (floridatax.us)."""

import re
from typing import Any, Optional

from app.extraction.schemas import TaxRecord

FLORIDA_TAX_PAGE_JS = """
() => {
  const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
  const fields = {};

  const assign = (key, value) => {
    if (value) fields[key] = value;
  };

  document.querySelectorAll('table tr').forEach((tr) => {
    const cells = [...tr.querySelectorAll('th, td')].map((c) => norm(c.innerText));
    if (cells.length >= 2 && cells[0] && cells[1]) {
      assign(cells[0].toLowerCase(), cells.slice(1).join(' | '));
    }
  });

  document.querySelectorAll('label, strong, b, span').forEach((el) => {
    const text = norm(el.innerText);
    if (!text || text.length > 80) return;
    const lower = text.toLowerCase();
    if (lower.endsWith(':')) {
      const key = lower.replace(/:$/, '');
      const sibling = el.parentElement;
      if (sibling) {
        const value = norm(sibling.innerText.replace(text, ''));
        if (value) assign(key, value);
      }
    }
  });

  const tables = [...document.querySelectorAll('table')].map((table, idx) => {
    const rows = [...table.querySelectorAll('tr')].map((tr) =>
      [...tr.querySelectorAll('th, td')].map((c) => norm(c.innerText)).filter(Boolean)
    ).filter((row) => row.length > 0);
    let headers = [];
    if (rows.length > 0) {
      const first = rows[0];
      if (first.every((cell) => cell.length < 40)) headers = first;
    }
    return { idx, headers, rows };
  });

  const yearlyDue = [];
  document.querySelectorAll('table tr, .year-row, li').forEach((row) => {
    const text = norm(row.innerText);
    const match = text.match(/^(20\\d{2})\\s+(.+?)\\s+\\$?([\\d,]+\\.\\d{2})/);
    if (match) {
      yearlyDue.push({ year: match[1], label: match[2], due: match[3] });
    }
  });

  return {
    title: document.title,
    url: location.href,
    fields,
    tables,
    yearly_due: yearlyDue,
    body_text: norm(document.body.innerText).slice(0, 12000),
  };
}
"""


def _parse_money(value: str | None) -> Optional[float]:
    if not value:
        return None
    match = re.search(r"[\d,]+\.?\d*", str(value).replace("$", ""))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def _field(data: dict[str, Any], *keys: str) -> Optional[str]:
    fields = data.get("fields") or {}
    for key in keys:
        for fk, fv in fields.items():
            if key in fk:
                return str(fv).strip() if fv else None
    body = data.get("body_text") or ""
    for key in keys:
        match = re.search(rf"{re.escape(key)}[:\\s]+([^\\n|]+)", body, re.I)
        if match:
            return match.group(1).strip()
    return None


def tax_record_from_florida_data(
    scraped: dict[str, Any],
    apn: Optional[str] = None,
    owner_name: Optional[str] = None,
) -> TaxRecord:
    fields = scraped.get("fields") or {}
    tax_account = scraped.get("account_number") or _field(scraped, "property tax account", "tax account") or fields.get("property tax account")
    tax_year = _field(scraped, "year", "tax year")
    
    last_two = scraped.get("last_two_bills") or []
    if not tax_year and last_two:
        first_b = last_two[0]
        b_summary = first_b.get("bill_summary") or {}
        b_name = b_summary.get("bill") or first_b.get("bill_title") or ""
        y_match = re.search(r"20\d{2}", b_name)
        if y_match:
            tax_year = y_match.group(0)

    bill_number = _field(scraped, "bill number")
    amount_due = scraped.get("amount_due")
    if amount_due is None:
        amount_due = _parse_money(_field(scraped, "this bill", "amount due", "due"))

    owner = owner_name or scraped.get("owner") or _field(scraped, "owner name", "owner")
    prop_address = scraped.get("situs") or _field(scraped, "property address", "situs")

    is_ct = bool(last_two or "county-taxes" in (scraped.get("url") or "") or scraped.get("account_history"))

    return TaxRecord(
        apn=apn,
        tax_account=tax_account,
        owner_name=owner,
        tax_year=tax_year,
        bill_number=bill_number,
        amount_due=amount_due,
        property_address=prop_address,
        mailing_address=_field(scraped, "mailing address"),
        source_url=scraped.get("url"),
        raw_json={
            "platform": "county-taxes" if is_ct else "floridatax.us",
            "tax_account": tax_account,
            "tax_year": tax_year,
            "bill_number": bill_number,
            "amount_due": amount_due,
            "amount_due_message": scraped.get("amount_due_message"),
            "last_payment": scraped.get("last_payment"),
            "property_address": prop_address,
            "mailing_address": _field(scraped, "mailing address"),
            "header_fields": fields,
            "account_history": scraped.get("account_history") or [],
            "last_two_bills": last_two,
            "downloaded_bills": scraped.get("downloaded_bills") or [],
            "exemptions_summary": scraped.get("exemptions_summary"),
            "yearly_due_summary": scraped.get("yearly_due") or [],
            "tabs": scraped.get("tabs") or {},
            "tables": scraped.get("tables") or [],
            "source_url": scraped.get("url"),
        },
    )
