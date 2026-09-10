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
    tax_account = _field(scraped, "property tax account", "tax account") or fields.get("property tax account")
    tax_year = _field(scraped, "year", "tax year")
    bill_number = _field(scraped, "bill number")
    amount_due = _parse_money(_field(scraped, "this bill", "amount due", "due"))

    return TaxRecord(
        apn=apn,
        tax_account=tax_account,
        owner_name=owner_name or _field(scraped, "owner name", "owner"),
        tax_year=tax_year,
        bill_number=bill_number,
        amount_due=amount_due,
        property_address=_field(scraped, "property address", "situs"),
        mailing_address=_field(scraped, "mailing address"),
        source_url=scraped.get("url"),
        raw_json={
            "platform": "floridatax.us",
            "tax_account": tax_account,
            "tax_year": tax_year,
            "bill_number": bill_number,
            "amount_due": amount_due,
            "mailing_address": _field(scraped, "mailing address"),
            "header_fields": fields,
            "yearly_due_summary": scraped.get("yearly_due") or [],
            "tabs": scraped.get("tabs") or {},
            "source_url": scraped.get("url"),
        },
    )
