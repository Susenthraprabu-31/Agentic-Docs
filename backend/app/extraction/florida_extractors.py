"""HTML/DOM extraction for Florida county property appraiser portals."""

import re
from typing import Any, Optional

from bs4 import BeautifulSoup

from app.extraction.schemas import ParcelRecord

FLORIDA_SCRAPE_JS = """
() => {
  const data = {};
  const clean = (t) => (t || '').replace(/\\s+/g, ' ').trim();

  // Label / value pairs in tables and definition lists
  document.querySelectorAll('tr, dl, .row, .detail-row, .property-row, mat-row').forEach(row => {
    const cells = row.querySelectorAll('th, td, dt, dd, label, span, div');
    if (cells.length < 2) return;
    const key = clean(cells[0].innerText || cells[0].textContent);
    const val = clean(cells[1].innerText || cells[1].textContent);
    if (key && val && key.length < 80 && val.length < 500 && key !== val) {
      data[key.toLowerCase()] = val;
    }
  });

  // Angular/material style: label above value
  document.querySelectorAll('label, .label, .field-label, strong, b').forEach(label => {
    const key = clean(label.innerText || label.textContent).replace(/:$/, '');
    if (!key || key.length > 80) return;
    const parent = label.closest('div, li, tr, .form-group, .field');
    if (!parent) return;
    const valEl = parent.querySelector('.value, .field-value, span:not(label span), p, div:nth-child(2)');
    const val = valEl ? clean(valEl.innerText || valEl.textContent) : '';
    if (val && val !== key) data[key.toLowerCase()] = val;
  });

  // Headings with adjacent content (common on SPA detail pages)
  document.querySelectorAll('h1, h2, h3, h4, .card-title, .section-title').forEach(h => {
    const key = clean(h.innerText || h.textContent).replace(/:$/, '');
    const sib = h.nextElementSibling;
    if (key && sib) {
      const val = clean(sib.innerText || sib.textContent);
      if (val && val.length < 500) data[key.toLowerCase()] = val;
    }
  });

  return data;
}
"""


def _clean(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    cleaned = re.sub(r"\s+", " ", text).strip()
    return cleaned or None


def _parse_value(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    match = re.search(r"[\d,]+\.?\d*", text.replace(",", ""))
    if match:
        try:
            return float(match.group())
        except ValueError:
            return None
    return None


def _pick_field(data: dict[str, Any], *keys: str) -> Optional[str]:
    for key in keys:
        val = data.get(key.lower())
        if val:
            return _clean(str(val))
    return None


def parcel_record_from_florida_data(data: dict[str, Any], source_url: str = "") -> ParcelRecord:
    apn = _pick_field(
        data,
        "parcel id",
        "parcel",
        "parcel number",
        "parcel #",
        "pin",
        "folio",
        "folio number",
        "property id",
        "tax id",
        "strap",
    )
    owner = _pick_field(
        data,
        "owner",
        "owner name",
        "owner(s)",
        "owner names",
        "property owner",
        "owner 1",
    )
    address = _pick_field(
        data,
        "site address",
        "property address",
        "situs address",
        "physical address",
        "location",
        "address",
        "mailing address",
    )
    legal = _pick_field(
        data,
        "legal description",
        "legal",
        "description",
        "subdivision",
    )
    value_text = _pick_field(
        data,
        "just value",
        "market value",
        "assessed value",
        "total assessed value",
        "total value",
        "land value",
        "building value",
    )

    sales: list[dict[str, Any]] = []
    for key, val in data.items():
        if "sale" in key and val:
            sales.append({"field": key, "value": val})

    raw = dict(data)
    if sales:
        raw["sales_hints"] = sales

    if source_url:
        raw["source_url"] = source_url

    return ParcelRecord(
        apn=apn,
        owner_name=owner,
        legal_desc=legal,
        assessed_value=_parse_value(value_text),
        property_address=address,
        source="assessor",
        raw_json=raw,
    )


FLORIDA_PA_DETAIL_JS = """
() => {
  const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
  const data = { sales_history: [], buildings: [], land: [], fields: {} };

  const cellValue = (label) => {
    const target = label.toLowerCase();
    for (const cell of document.querySelectorAll('td, th')) {
      const text = norm(cell.innerText).toLowerCase().replace(/:$/, '').replace(/\\*+$/, '');
      if (text !== target) continue;
      const row = cell.closest('tr');
      if (!row) continue;
      const cells = [...row.querySelectorAll('td, th')];
      const idx = cells.indexOf(cell);
      if (idx >= 0 && cells[idx + 1]) {
        return norm(cells[idx + 1].innerText);
      }
    }
    return '';
  };

  const bodyText = document.body.innerText || '';
  const parcelMatch = bodyText.match(/Parcel:\\s*([0-9]{2}-[0-9]{2}-[0-9]{2}-[0-9]{5}-[0-9]{3}(?:\\s*\\(\\d+\\))?)/i);
  data.parcel = (parcelMatch ? norm(parcelMatch[1]) : '') || cellValue('parcel');
  data.owner = cellValue('owner');
  data.site = cellValue('site');
  data.description = cellValue('description') || cellValue('description*');
  data.area = cellValue('area');
  data.section_township_range = cellValue('s/t/r');
  data.use_code = cellValue('use code');
  data.tax_district = cellValue('tax district');

  const assessedMatches = [...bodyText.matchAll(/Assessed[\\s\\n]+\\$([\\d,]+)/gi)];
  if (assessedMatches.length) {
    data.assessed_value = '$' + assessedMatches[assessedMatches.length - 1][1];
  }
  const justMatches = [...bodyText.matchAll(/Just[\\s\\n]+\\$([\\d,]+)/gi)];
  if (justMatches.length) {
    data.just_value = '$' + justMatches[justMatches.length - 1][1];
  }

  document.querySelectorAll('table').forEach((table) => {
    const rows = [...table.querySelectorAll('tr')];
    if (rows.length < 2) return;
    const headerCells = [...rows[0].querySelectorAll('th, td')].map((c) => norm(c.innerText).toLowerCase());
    if (headerCells[0] === 'sale date' && headerCells[1] === 'sale price') {
      rows.slice(1).forEach((tr) => {
        const cells = [...tr.querySelectorAll('td')].map((c) => norm(c.innerText));
        if (cells.length >= 4 && /^\\d/.test(cells[0])) {
          data.sales_history.push({
            sale_date: cells[0],
            sale_price: cells[1],
            book_page: cells[2],
            deed_type: cells[3],
            vi: cells[4] || '',
            qualification: cells[5] || '',
            rcode: cells[6] || '',
          });
        }
      });
    }
    if (headerCells.includes('year blt') && headerCells.includes('bldg value')) {
      rows.slice(1).forEach((tr) => {
        const cells = [...tr.querySelectorAll('td')].map((c) => norm(c.innerText));
        if (cells.length >= 6 && cells[0].toLowerCase() === 'sketch' && /^\\d{4}$/.test(cells[2])) {
          data.buildings.push({
            sketch: cells[0],
            description: cells[1],
            year_built: cells[2],
            base_sf: cells[3],
            actual_sf: cells[4],
            building_value: cells[5],
          });
        }
      });
    }
    if (headerCells.includes('land value') && headerCells.includes('eff rate')) {
      rows.slice(1).forEach((tr) => {
        const cells = [...tr.querySelectorAll('td')].map((c) => norm(c.innerText));
        if (cells.length >= 5 && /^\\d+$/.test(cells[0]) && /SF|AC/i.test(cells[2])) {
          data.land.push({
            code: cells[0],
            description: cells[1],
            units: cells[2],
            adjustments: cells[3],
            eff_rate: cells[4],
            land_value: cells[5] || '',
          });
        }
      });
    }
  });

  return data;
}
"""


def _split_florida_pa_owner(owner_block: str) -> tuple[str | None, str | None, str]:
    block = re.sub(r"\s+", " ", owner_block or "").strip()
    if not block:
        return None, None, ""

    addr_match = re.search(r"\b(\d{1,6}\s+[NSEW]?\s*)", block)
    if not addr_match:
        return block, None, block

    names_part = block[: addr_match.start()].strip()
    mailing_address = block[addr_match.start() :].strip()
    tokens = names_part.split()
    owner_name = names_part
    for i in range(1, len(tokens)):
        if i >= 4 and tokens[i] == tokens[0]:
            owner_name = " ".join(tokens[:i])
            break
    else:
        owner_name = " ".join(tokens[:5]) if len(tokens) > 5 else names_part

    return owner_name or None, mailing_address or None, names_part


def _florida_pa_sales_to_chain(sales: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chain: list[dict[str, Any]] = []
    for sale in sales:
        if not isinstance(sale, dict):
            continue
        chain.append(
            {
                "recording_date": sale.get("sale_date"),
                "sale_price": _parse_value(sale.get("sale_price")),
                "book_page": sale.get("book_page"),
                "document_type": sale.get("deed_type") or "Sale",
                "instrument_number": None,
                "grantor": None,
                "grantee": None,
            }
        )
    return chain


def parcel_record_from_florida_pa_detail(data: dict[str, Any], source_url: str = "") -> ParcelRecord:
    parcel_raw = data.get("parcel") or data.get("fields", {}).get("parcel", "")
    parcel_raw = re.sub(r"\s*\(\d+\)\s*", "", str(parcel_raw)).strip()
    parcel_raw = re.sub(r"\s+", "-", parcel_raw)
    if re.fullmatch(r"\d{2}-\d{2}-\d{2}-\d{5}-\d{3}", parcel_raw):
        pass
    elif re.search(r"\d{14}", parcel_raw.replace("-", "")):
        from app.config.florida_portals import normalize_florida_pa_parcel

        parcel_raw = normalize_florida_pa_parcel(parcel_raw)

    owner_block = (data.get("owner") or "").replace("\r\n", "\n")
    owner_lines = [line.strip() for line in owner_block.split("\n") if line.strip()]
    if len(owner_lines) > 1:
        owner_name = owner_lines[0]
        mailing_address = ", ".join(owner_lines[1:])
        all_owners = owner_block
    else:
        owner_name, mailing_address, all_owners = _split_florida_pa_owner(owner_block)

    value_text = data.get("assessed_value") or data.get("just_value")

    raw: dict[str, Any] = {
        "source_url": source_url,
        "platform": "floridapa.com",
        "parcel_detail": data,
        "owners": all_owners,
        "mailing_address": mailing_address,
        "area": data.get("area"),
        "section_township_range": data.get("section_township_range"),
        "use_code": data.get("use_code"),
        "tax_district": data.get("tax_district"),
        "sales_history": data.get("sales_history") or [],
        "building_characteristics": data.get("buildings") or [],
        "land_breakdown": data.get("land") or [],
        "assessment_fields": data.get("fields") or {},
        "chain_of_title": _florida_pa_sales_to_chain(data.get("sales_history") or []),
    }

    return ParcelRecord(
        apn=parcel_raw or None,
        owner_name=owner_name,
        legal_desc=data.get("description"),
        assessed_value=_parse_value(value_text),
        property_address=data.get("site"),
        source="assessor",
        raw_json=raw,
    )


def extract_florida_parcel_from_html(html: str, source_url: str = "") -> ParcelRecord:
    soup = BeautifulSoup(html, "lxml")
    data: dict[str, Any] = {}

    for row in soup.select("tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) >= 2:
            key = _clean(cells[0].get_text())
            val = _clean(cells[1].get_text())
            if key and val:
                data[key.lower()] = val

    for label in soup.select("label, .label, .field-label, dt, th, strong"):
        key = _clean(label.get_text())
        if not key:
            continue
        val_el = (
            label.find_next(["dd", "td", "span", "div", "p"])
            or label.find_next_sibling()
        )
        if val_el:
            val = _clean(val_el.get_text())
            if val and val.lower() != key.lower().rstrip(":"):
                data[key.lower().rstrip(":")] = val

    # Orange OCPA card sections
    for card in soup.select(".card, .panel, .property-card, mat-card"):
        title = card.select_one("h1, h2, h3, h4, .card-title, .panel-title")
        if title:
            key = _clean(title.get_text())
            body = _clean(card.get_text())
            if key and body:
                data[key.lower()] = body

    return parcel_record_from_florida_data(data, source_url)
