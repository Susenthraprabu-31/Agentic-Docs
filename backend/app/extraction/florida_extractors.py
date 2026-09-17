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


def _parse_currency_value(text: Optional[str]) -> Optional[float]:
    """Parse dollar amounts; ignore bare years like 2026 mistaken for assessed value."""
    if not text:
        return None
    raw = str(text).strip()
    if "$" in raw:
        return _parse_value(raw)
    val = _parse_value(raw)
    if val is None:
        return None
    if 2000 <= val <= 2035 and "." not in raw.replace(",", ""):
        return None
    if val >= 1000:
        return val
    return None


_GARBAGE_ASSESSOR_MARKERS = (
    "search criteria",
    "back to search",
    "property search",
    "subdivision name folio",
    "owner name subdivision",
    "111 nw 1 st suite",
)

MIAMI_DADE_FOLIO_RE = re.compile(r"^\d{2}-\d{4}-\d{3}-\d{4}$")
MIAMI_DADE_FOLIO_FIND_RE = re.compile(r"\b(\d{2}-\d{4}-\d{3}-\d{4})\b")


def extract_valid_miami_dade_folio(*candidates: Optional[str]) -> Optional[str]:
    for raw in candidates:
        if not raw:
            continue
        text = re.sub(r"\s+", " ", str(raw)).strip()
        if MIAMI_DADE_FOLIO_RE.match(text):
            return text
        match = MIAMI_DADE_FOLIO_FIND_RE.search(text)
        if match:
            return match.group(1)
        digits = re.sub(r"\D", "", text)
        if len(digits) == 13:
            from app.config.florida_portals import normalize_florida_parcel

            return normalize_florida_parcel(digits, county="miami-dade")
    return None


def is_valid_miami_dade_legal_desc(text: Optional[str]) -> bool:
    if not text:
        return False
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) < 25:
        return False
    if re.match(r"^(patio|wall|pool|shed|carport)\s*[-–]", cleaned, re.I):
        return False
    if re.search(r"\$\s*[\d,]+\s*$", cleaned) and len(cleaned) < 80:
        return False
    return True


def is_garbage_assessor_text(text: Optional[str]) -> bool:
    if not text:
        return True
    lower = re.sub(r"\s+", " ", text).strip().lower()
    if not lower:
        return True
    if any(marker in lower for marker in _GARBAGE_ASSESSOR_MARKERS):
        return True
    if len(lower) > 350:
        return True
    return False


def is_valid_miami_dade_extraction(parcel: ParcelRecord) -> bool:
    if not parcel.apn or not MIAMI_DADE_FOLIO_RE.match(str(parcel.apn)):
        return False
    if is_garbage_assessor_text(parcel.owner_name):
        return False
    if is_garbage_assessor_text(parcel.property_address):
        return False
    if parcel.property_address and len(parcel.property_address) > 220:
        return False
    return bool(parcel.owner_name or parcel.property_address)


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


MIAMI_DADE_DETAIL_JS = """
() => {
  const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
  const FOLIO_RE = /\\b(\\d{2}-\\d{4}-\\d{3}-\\d{4})\\b/;
  const data = {
    fields: {},
    sections: {},
    sales_history: [],
    assessment_information: [],
    benefits_information: [],
    taxable_value_information: [],
    land_information: {},
    building_information: {},
    extra_features: [],
    additional_information: {},
  };
  const bodyText = document.body.innerText || '';

  const isGarbage = (text) => /search criteria|back to search|property search|111 nw 1 st|^search:?$/i.test(text || '');

  const addField = (key, val) => {
    if (!key || !val || isGarbage(key) || isGarbage(val)) return;
    const k = norm(key).toLowerCase().replace(/[:#*]/g, '').trim();
    const v = norm(val);
    if (!v || v.length > 500 || k === v.toLowerCase()) return;
    data.fields[k] = v;
  };

  const sliceSection = (startPattern, endPattern) => {
    const start = bodyText.search(startPattern);
    if (start < 0) return '';
    const chunk = bodyText.slice(start);
    const end = chunk.search(endPattern);
    return end > 0 ? chunk.slice(0, end) : chunk.slice(0, 4000);
  };

  const propertySection = sliceSection(/PROPERTY INFORMATION/i, /Featured Online Tools|ASSESSMENT INFORMATION/i);
  const propertyLines = propertySection.split('\\n').map(norm).filter(Boolean);
  const propertyMap = {
    'folio #': 'folio',
    folio: 'folio',
    'sub-division': 'subdivision',
    subdivision: 'subdivision',
    'property address': 'property_address',
    owner: 'owner',
    'mailing address': 'mailing_address',
    'pa primary zone': 'pa_primary_zone',
    'pa secondary zone': 'pa_secondary_zone',
    'primary land use': 'primary_land_use',
    'lot size': 'lot_size',
    floors: 'floors',
    'living units': 'living_units',
    'actual area': 'actual_area',
    'living area': 'living_area',
    'adjusted area': 'adjusted_area',
    'year built': 'year_built',
  };

  for (let i = 0; i < propertyLines.length; i++) {
    const line = propertyLines[i];
    const key = line.toLowerCase().replace(/[:#]/g, '').trim();
    const folioInline = line.match(/folio\\s*#?\\s*:?\\s*(\\d{2}-\\d{4}-\\d{3}-\\d{4})/i);
    if (folioInline) {
      data.folio = folioInline[1];
      data.fields.folio = folioInline[1];
      continue;
    }
    const isNextPropertyKey = (candidate) => {
      const k = candidate.toLowerCase().replace(/[:#]/g, '').trim();
      return (
        Boolean(propertyMap[k])
        || /^(\\d+)\\s*\\/\\s*(\\d+)\\s*\\/\\s*(\\d+)$/.test(candidate)
        || /^[\\d,]+\\s*Sq\\.?\\s*Ft/i.test(candidate)
        || /^Year Built$/i.test(candidate)
      );
    };
    if (propertyMap[key] && i + 1 < propertyLines.length) {
      const values = [];
      let j = i + 1;
      while (j < propertyLines.length && !isNextPropertyKey(propertyLines[j])) {
        if (!isGarbage(propertyLines[j])) values.push(propertyLines[j]);
        j += 1;
      }
      const val = values.join(' ').trim();
      if (val && val.length < 400) {
        data[propertyMap[key]] = val;
        data.fields[propertyMap[key]] = val;
        i = Math.max(i, j - 1);
      }
      continue;
    }
    const bedMatch = line.match(/^(\\d+)\\s*\\/\\s*(\\d+)\\s*\\/\\s*(\\d+)$/);
    if (bedMatch) {
      data.bedrooms = bedMatch[1];
      data.bathrooms = bedMatch[2];
      data.half_baths = bedMatch[3];
    }
  }

  if (!data.folio) {
    const folioMatch = propertySection.match(FOLIO_RE) || bodyText.match(FOLIO_RE);
    if (folioMatch) {
      data.folio = folioMatch[1];
      data.fields.folio = folioMatch[1];
    }
  }

  const SECTION_MARKERS = [
    'PROPERTY INFORMATION',
    'Featured Online Tools',
    'ASSESSMENT INFORMATION',
    'BENEFITS INFORMATION',
    'TAXABLE VALUE INFORMATION',
    'FULL LEGAL DESCRIPTION',
    'SALES INFORMATION',
    'LAND INFORMATION',
    'BUILDING INFORMATION',
    'EXTRA FEATURES',
    'ADDITIONAL INFORMATION',
  ];

  const splitBodyIntoSections = (text) => {
    const sections = {};
    const upper = text.toUpperCase();
    const positions = SECTION_MARKERS
      .map((name) => ({ name, pos: upper.indexOf(name.toUpperCase()) }))
      .filter((x) => x.pos >= 0)
      .sort((a, b) => a.pos - b.pos);
    for (let i = 0; i < positions.length; i++) {
      const start = positions[i].pos + positions[i].name.length;
      const end = i + 1 < positions.length ? positions[i + 1].pos : text.length;
      sections[positions[i].name.toLowerCase()] = text.slice(start, end);
    }
    return sections;
  };

  const sectionBlocks = splitBodyIntoSections(bodyText);

  const parseYearsFromText = (text) => {
    const found = text.match(/\\b(20\\d{2})\\b/g);
    if (!found) return ['2026', '2025', '2024'];
    return [...new Set(found)].sort((a, b) => Number(b) - Number(a));
  };

  const extractDomTable = (title) => {
    const el = findSectionElement(title);
    if (!el) return null;
    let container = el.parentElement;
    for (let i = 0; i < 6 && container; i++) {
      const table = container.querySelector('table');
      if (table) {
        const grid = [...table.querySelectorAll('tr')]
          .map((tr) => [...tr.querySelectorAll('th, td')].map((c) => norm(c.innerText)))
          .filter((r) => r.some(Boolean));
        if (grid.length >= 2) {
          return { headers: grid[0], rows: grid.slice(1) };
        }
      }
      container = container.parentElement;
    }
    return null;
  };

  const findSectionElement = (title) => {
    const target = title.toUpperCase();
    for (const el of document.querySelectorAll('div, span, h2, h3, h4, th, label, p')) {
      const t = norm(el.innerText);
      if (t.toUpperCase() === target && t.length < 80) return el;
    }
    return null;
  };

  const parseAssessmentTable = (text) => {
    const years = parseYearsFromText(text);
    const headers = ['', ...years];
    const lines = text.split('\\n').map(norm).filter((l) => l && l !== '(i)');
    const rows = [];
    const metrics = ['Land Value', 'Building Value', 'Extra Feature Value', 'Market Value', 'Assessed Value'];

    for (const metric of metrics) {
      for (const line of lines) {
        if (line.toLowerCase().startsWith(metric.toLowerCase()) && line.includes('$')) {
          const vals = [...line.matchAll(/\\$[\\d,]+/g)].map((x) => x[0]).slice(0, years.length);
          if (vals.length) {
            rows.push([metric, ...vals]);
            break;
          }
        }
      }
      if (rows.some((r) => r[0] === metric)) continue;
      const idx = lines.findIndex((l) => l.toLowerCase() === metric.toLowerCase());
      if (idx >= 0) {
        const vals = [];
        for (let j = idx + 1; j < lines.length && vals.length < years.length; j++) {
          if (/^\\$[\\d,]+$/.test(lines[j])) vals.push(lines[j]);
          else if (metrics.some((m2) => lines[j].toLowerCase().startsWith(m2.toLowerCase()))) break;
          else if (/^(COUNTY|SCHOOL|BENEFITS|TAXABLE)/i.test(lines[j])) break;
        }
        if (vals.length) rows.push([metric, ...vals]);
      }
    }
    return { headers, rows };
  };

  const parseBenefitsTable = (text) => {
    const years = parseYearsFromText(text);
    const headers = ['Benefit', 'Type', ...years];
    const lines = text.split('\\n').map(norm).filter((l) => l && l !== '(i)');
    const rows = [];
    const known = [
      ['Save Our Homes Cap', 'Assessment Reduction'],
      ['Homestead', 'Exemption'],
      ['Second Homestead', 'Exemption'],
      ['Senior Homestead', 'Exemption'],
      ['Widow', 'Exemption'],
    ];

    for (const [benefit, defaultType] of known) {
      const idx = lines.findIndex((l) => l.toLowerCase().includes(benefit.toLowerCase()));
      if (idx < 0) continue;
      let typeVal = defaultType;
      let start = idx + 1;
      if (lines[start] && /reduction|exemption/i.test(lines[start]) && !/^\\$/.test(lines[start])) {
        typeVal = lines[start];
        start += 1;
      }
      const vals = [];
      for (let j = start; j < lines.length && vals.length < years.length; j++) {
        if (/^\\$[\\d,]+$/.test(lines[j])) vals.push(lines[j]);
        else if (known.some(([b]) => lines[j].toLowerCase().includes(b.toLowerCase()))) break;
      }
      if (vals.length) rows.push([benefit, typeVal, ...vals]);
    }
    return { headers, rows };
  };

  const parseTaxableTable = (text) => {
    const years = parseYearsFromText(text);
    const headers = ['', ...years];
    const lines = text.split('\\n').map(norm).filter(Boolean);
    const rows = [];
    let jurisdiction = '';

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (/^(COUNTY|SCHOOL BOARD|CITY|REGIONAL)$/i.test(line)) {
        jurisdiction = line;
        continue;
      }
      if (!jurisdiction) continue;
      if (/^exemption value$/i.test(line)) {
        const vals = [];
        for (let j = i + 1; j < lines.length && vals.length < years.length; j++) {
          if (/^\\$[\\d,]+$/.test(lines[j])) vals.push(lines[j]);
          else break;
        }
        if (vals.length) rows.push([`${jurisdiction} — Exemption Value`, ...vals]);
        continue;
      }
      if (/^taxable value$/i.test(line)) {
        const vals = [];
        for (let j = i + 1; j < lines.length && vals.length < years.length; j++) {
          if (/^\\$[\\d,]+$/.test(lines[j])) vals.push(lines[j]);
          else break;
        }
        if (vals.length) rows.push([`${jurisdiction} — Taxable Value`, ...vals]);
        continue;
      }
      const dollars = [...line.matchAll(/\\$[\\d,]+/g)].map((x) => x[0]);
      if (!dollars.length) continue;
      let label = line.replace(jurisdiction, '').split('$')[0].trim();
      if (/exemption value/i.test(line)) label = `${jurisdiction} — Exemption Value`;
      else if (/taxable value/i.test(line)) label = `${jurisdiction} — Taxable Value`;
      else if (label) label = `${jurisdiction} — ${label}`;
      else continue;
      rows.push([label, ...dollars.slice(0, years.length)]);
    }
    return { headers, rows };
  };

  const parseSalesTableText = (text) => {
    const headers = ['Previous Sale', 'Price', 'OR Book-Page', 'Qualification Description', 'Previous Owner 1'];
    const lines = text.split('\\n').map(norm).filter(Boolean);
    const rows = [];
    for (let i = 0; i < lines.length; i++) {
      if (!/^\\d{1,2}\\/\\d{1,2}\\/\\d{4}$/.test(lines[i])) continue;
      const row = [lines[i], '', '', '', ''];
      for (let j = i + 1; j < Math.min(i + 8, lines.length); j++) {
        if (/^\\d{1,2}\\/\\d{1,2}\\/\\d{4}$/.test(lines[j])) break;
        if (!row[1] && /^\\$/.test(lines[j])) row[1] = lines[j];
        else if (!row[2] && /\\d+\\s*\\/\\s*\\d+/.test(lines[j])) row[2] = lines[j];
        else if (!row[3] && lines[j].length > 8 && !/^\\$/.test(lines[j]) && !/^[A-Z ]{2,15}$/.test(lines[j])) row[3] = lines[j];
        else if (!row[4] && /^[A-Z]/.test(lines[j]) && lines[j].length > 4) row[4] = lines[j];
      }
      rows.push(row);
    }
    return { headers, rows };
  };

  const parseLandBuildingTable = (text) => {
    const lines = text.split('\\n').map(norm).filter((l) => l && !/information$/i.test(l));
    const rows = [];
    for (let i = 0; i < lines.length - 1; i++) {
      const label = lines[i];
      const value = lines[i + 1];
      if (label.length > 45 || /^\\$/.test(label) || /^\\d{1,2}\\/\\d/.test(label)) continue;
      if (!value || value.length > 150 || /^\\d{1,2}\\/\\d{1,2}\\/\\d{4}$/.test(value)) continue;
      rows.push([label, value]);
      i += 1;
    }
    return { headers: ['', ''], rows };
  };

  const parseExtraFeaturesTable = (text) => {
    const headers = ['', 'Year Built', 'Units', 'Calc Value'];
    const lines = text.split('\\n').map(norm).filter(Boolean);
    const rows = [];
    for (let i = 0; i < lines.length; i++) {
      if (!/^(patio|wall|pool|shed|carport|fence|roof|driveway|utility)/i.test(lines[i])) continue;
      rows.push([
        lines[i],
        /^\\d{4}$/.test(lines[i + 1] || '') ? lines[i + 1] : '',
        /^[\\d,]+$/.test(lines[i + 2] || '') ? lines[i + 2] : '',
        /^\\$/.test(lines[i + 3] || '') ? lines[i + 3] : '',
      ]);
    }
    return { headers, rows };
  };

  const parseLegalSection = (text) => {
    return text.split('\\n').map(norm).filter((l) => (
      l
      && !/full legal description/i.test(l)
      && !/sales information/i.test(l)
      && !/sales transaction history/i.test(l)
      && !/previous sale/i.test(l)
    )).join('\\n').slice(0, 2000);
  };

  const pickTable = (title, text, textParser) => extractDomTable(title) || textParser(text);

  data.assessment_information_table = pickTable(
    'ASSESSMENT INFORMATION',
    sectionBlocks['assessment information'] || '',
    parseAssessmentTable,
  );
  data.benefits_information_table = pickTable(
    'BENEFITS INFORMATION',
    sectionBlocks['benefits information'] || '',
    parseBenefitsTable,
  );
  data.taxable_value_information_table = pickTable(
    'TAXABLE VALUE INFORMATION',
    sectionBlocks['taxable value information'] || '',
    parseTaxableTable,
  );
  data.sales_information_table = pickTable(
    'SALES INFORMATION',
    sectionBlocks['sales information'] || '',
    parseSalesTableText,
  );
  data.land_information_table = pickTable(
    'LAND INFORMATION',
    sectionBlocks['land information'] || '',
    parseLandBuildingTable,
  );
  data.building_information_table = pickTable(
    'BUILDING INFORMATION',
    sectionBlocks['building information'] || '',
    parseLandBuildingTable,
  );
  data.extra_features_table = pickTable(
    'EXTRA FEATURES',
    sectionBlocks['extra features'] || '',
    parseExtraFeaturesTable,
  );

  data.sales_history = (data.sales_information_table.rows || []).map((row) => ({
    sale_date: row[0] || '',
    sale_price: row[1] || '',
    book_page: row[2] || '',
    qualification: row[3] || '',
    previous_owner: row[4] || '',
    deed_type: 'Sale',
  }));

  const legalText = sectionBlocks['full legal description'] || '';
  if (legalText) {
    data.full_legal_description = parseLegalSection(legalText);
    data.legal_description = data.full_legal_description;
    if (data.full_legal_description) data.fields['full legal description'] = data.full_legal_description;
  }

  const additionalText = sectionBlocks['additional information'] || '';
  if (additionalText) {
    data.additional_information = { body_text: additionalText.slice(0, 4000) };
    data.sections['additional information'] = additionalText.slice(0, 3000);
  }

  for (const [name, text] of Object.entries(sectionBlocks)) {
    if (text && name !== 'property information' && name !== 'featured online tools') {
      data.sections[name] = text.slice(0, 3000);
    }
  }

  const assessedRow = (data.assessment_information_table?.rows || []).find((row) => /assessed value/i.test(row[0] || ''));
  if (assessedRow) {
    const yearVal = assessedRow[1] || assessedRow[2] || assessedRow[3];
    if (yearVal) data.assessed_value = yearVal.startsWith('$') ? yearVal : `$${yearVal}`;
  }
  if (!data.assessed_value) {
    const assessedMatches = [...bodyText.matchAll(/Assessed Value\\s+\\$?([\\d,]+)/gi)];
    if (assessedMatches.length) data.assessed_value = `$${assessedMatches[assessedMatches.length - 1][1]}`;
  }

  const marketRow = (data.assessment_information_table?.rows || []).find((row) => /market value/i.test(row[0] || ''));
  if (marketRow) {
    data.market_value = marketRow[1] || marketRow[2] || marketRow[3] || '';
  }

  if (!data.property_address) {
    const m = bodyText.match(/Property Address\\s*\\n\\s*([^\\n]{5,100})/i);
    if (m) data.property_address = norm(m[1]);
  }
  if (!data.owner) {
    const m = bodyText.match(/Owner\\s*\\n\\s*([^\\n]{3,120})/i);
    if (m && !isGarbage(m[1])) data.owner = norm(m[1]);
  }

  data.site = data.property_address;
  return data;
}
"""


def parcel_record_from_miami_dade_detail(data: dict[str, Any], source_url: str = "") -> ParcelRecord:
    fields = data.get("fields") if isinstance(data.get("fields"), dict) else {}

    folio = extract_valid_miami_dade_folio(
        data.get("folio"),
        fields.get("folio"),
        fields.get("folio #"),
    )

    owner_block = (data.get("owner") or fields.get("owner") or "").replace("\r\n", "\n")
    owner_lines = [line.strip() for line in owner_block.split("\n") if line.strip()]
    if owner_lines:
        owner_name = " ".join(owner_lines)
    else:
        owner_name = owner_block or None
    if is_garbage_assessor_text(owner_name):
        owner_name = None

    value_text = data.get("assessed_value") or fields.get("assessed_value")
    site = data.get("property_address") or data.get("site") or fields.get("property address")
    if is_garbage_assessor_text(site):
        site = None

    description = (
        data.get("full_legal_description")
        or data.get("legal_description")
        or fields.get("full legal description")
    )
    if description:
        description = re.sub(
            r"\s*(Sales Transaction History|Previous Sale|SALES INFORMATION).*$",
            "",
            str(description),
            flags=re.I | re.M,
        ).strip()
    if not is_valid_miami_dade_legal_desc(description):
        description = data.get("subdivision") or fields.get("sub-division") or fields.get("subdivision")

    primary_land_use = data.get("primary_land_use") or fields.get("primary land use") or ""
    if primary_land_use:
        bed_in_use = re.search(r"(\d+)\s*/\s*(\d+)\s*/\s*(\d+)", primary_land_use)
        if bed_in_use:
            primary_land_use = primary_land_use[: bed_in_use.start()].strip(" :")
            if not data.get("bedrooms"):
                data["bedrooms"] = bed_in_use.group(1)
                data["bathrooms"] = bed_in_use.group(2)
                data["half_baths"] = bed_in_use.group(3)

    sales = data.get("sales_history") or []
    mailing_address = data.get("mailing_address") or fields.get("mailing address")

    raw: dict[str, Any] = {
        "source_url": source_url,
        "platform": "miamidadepa.gov",
        "parcel_detail": data,
        "fields": fields,
        "sections": data.get("sections") or {},
        "folio": folio,
        "owner": owner_name,
        "mailing_address": mailing_address,
        "subdivision": data.get("subdivision") or fields.get("sub-division") or fields.get("subdivision"),
        "pa_primary_zone": data.get("pa_primary_zone") or fields.get("pa primary zone"),
        "pa_secondary_zone": data.get("pa_secondary_zone") or fields.get("pa secondary zone"),
        "primary_land_use": primary_land_use or None,
        "lot_size": data.get("lot_size") or fields.get("lot size"),
        "actual_area": data.get("actual_area") or fields.get("actual area"),
        "adjusted_area": data.get("adjusted_area") or fields.get("adjusted area"),
        "floors": data.get("floors") or fields.get("floors"),
        "living_units": data.get("living_units") or fields.get("living units"),
        "bedrooms": data.get("bedrooms"),
        "bathrooms": data.get("bathrooms"),
        "half_baths": data.get("half_baths"),
        "living_area": data.get("living_area") or fields.get("living area"),
        "year_built": data.get("year_built") or fields.get("year built"),
        "market_value": data.get("market_value"),
        "assessed_value_text": value_text,
        "assessment_information_table": data.get("assessment_information_table") or {"headers": [], "rows": []},
        "benefits_information_table": data.get("benefits_information_table") or {"headers": [], "rows": []},
        "taxable_value_information_table": data.get("taxable_value_information_table") or {"headers": [], "rows": []},
        "sales_information_table": data.get("sales_information_table") or {"headers": [], "rows": []},
        "land_information_table": data.get("land_information_table") or {"headers": [], "rows": []},
        "building_information_table": data.get("building_information_table") or {"headers": [], "rows": []},
        "extra_features_table": data.get("extra_features_table") or {"headers": [], "rows": []},
        "additional_information": data.get("additional_information") or {},
        "full_legal_description": data.get("full_legal_description") or description,
        "sales_history": sales,
        "chain_of_title": _florida_pa_sales_to_chain(sales),
    }

    return ParcelRecord(
        apn=folio,
        owner_name=owner_name,
        legal_desc=description,
        assessed_value=_parse_currency_value(value_text),
        property_address=site,
        source="assessor",
        raw_json=raw,
    )


def normalize_miami_dade_folio(folio: str) -> str:
    from app.config.florida_portals import normalize_florida_parcel

    return normalize_florida_parcel(folio, county="miami-dade")
