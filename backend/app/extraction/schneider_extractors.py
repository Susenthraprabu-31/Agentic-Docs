"""Extract property data from Schneider Corp / qPublic detail pages."""

import re
from typing import Any, Optional

from bs4 import BeautifulSoup

from app.extraction.html_extractors import _clean, _parse_value
from app.extraction.schemas import ParcelRecord

SCHNEIDER_SCRAPE_JS = """
() => {
  const data = {};
  const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();

  const PARCEL_LABELS = [
    'Parcel Number', 'Location Address', 'Project Name', 'Legal Information',
    'Property Class', 'Land Area (Acres)', 'Land Area',
  ];

  const setField = (key, val) => {
    if (!key || !val) return;
    if (val.toLowerCase() === key.toLowerCase()) return;
    if (/owner type/i.test(val)) return;
    data[key] = val;
  };

  const idFieldMap = [
    ['Parcel Number', ['lblParcelID', 'lblParcel', 'ParcelID']],
    ['Location Address', ['lblLocationAddress', 'lblLocation', 'lblSitusAddress', 'lblSitus', 'LocationAddress']],
    ['Legal Information', ['lblLegalInformation', 'lblLegalDescription', 'lblLegal', 'LegalInformation', 'LegalDescription']],
    ['Project Name', ['lblProjectName', 'lblProject', 'ProjectName']],
    ['Property Class', ['lblPropertyClass', 'lblClass', 'PropertyClass']],
    ['Land Area (Acres)', ['lblLandArea', 'lblAcres', 'LandArea']],
  ];

  idFieldMap.forEach(([label, idParts]) => {
    for (const part of idParts) {
      const el = document.querySelector(`[id*="${part}"]`);
      if (!el || el.classList.contains('widgetLabel')) continue;
      const val = norm(el.textContent || el.value);
      if (val && val !== label) {
        setField(label, val);
        break;
      }
    }
  });

  const findValueForLabel = (labelEl) => {
    if (labelEl.nextElementSibling) {
      const sib = labelEl.nextElementSibling;
      const sibText = norm(sib.textContent || sib.value);
      if (sibText && sibText !== norm(labelEl.textContent)) return sibText;
    }
    const row = labelEl.closest('tr');
    if (row) {
      const valueCell = row.querySelector('.widgetValue, td:last-child, span:last-child');
      if (valueCell && valueCell !== labelEl) {
        const val = norm(valueCell.textContent || valueCell.value);
        if (val) return val;
      }
    }
    const parent = labelEl.parentElement;
    if (parent) {
      const valueEl = parent.querySelector('.widgetValue, [id*="lbl"]:not(.widgetLabel)');
      if (valueEl && valueEl !== labelEl) {
        const val = norm(valueEl.textContent || valueEl.value);
        if (val) return val;
      }
    }
    return '';
  };

  const extractFromPaneText = () => {
    const text = document.querySelector('#ctlBodyPane')?.innerText || '';
    if (!text) return;
    const patterns = [
      ['Parcel Number', /Parcel Number\\s*\\n\\s*([^\\n]+)/i],
      ['Location Address', /Location Address\\s*\\n\\s*([^\\n]+)/i],
      ['Project Name', /Project Name\\s*\\n\\s*([^\\n]+)/i],
      ['Legal Information', /Legal Information\\s*\\n\\s*([\\s\\S]+?)\\n\\s*Property Class/i],
      ['Property Class', /Property Class\\s*\\n\\s*([^\\n]+)/i],
      ['Land Area (Acres)', /Land Area \\(Acres\\)\\s*\\n\\s*([^\\n]+)/i],
    ];
    patterns.forEach(([label, regex]) => {
      const match = text.match(regex);
      if (match?.[1]) setField(label, norm(match[1]));
    });
  };

  const extractParcelInformationSection = () => {
    const addLabelValue = (labelText, valueText) => {
      if (valueText && valueText !== labelText) setField(labelText, valueText);
    };

    document.querySelectorAll('#ctlBodyPane [id*="lbl"]').forEach((el) => {
      const id = (el.id || '').toLowerCase();
      const text = norm(el.textContent || el.value);
      if (!text || PARCEL_LABELS.includes(text) || /owner type/i.test(text)) return;
      if (el.classList.contains('widgetLabel')) return;
      if (id.includes('parcelid') || (id.includes('parcel') && !id.includes('map'))) addLabelValue('Parcel Number', text);
      else if (id.includes('locationaddress') || id.includes('situsaddress') || (id.includes('situs') && !id.includes('map'))) addLabelValue('Location Address', text);
      else if (id.includes('legalinformation') || id.includes('legaldescription') || id.includes('legaldesc')) addLabelValue('Legal Information', text);
      else if (id.includes('projectname') || (id.includes('project') && !id.includes('map'))) addLabelValue('Project Name', text);
      else if (id.includes('propertyclass')) addLabelValue('Property Class', text);
    });

    document.querySelectorAll('#ctlBodyPane h2, #ctlBodyPane h3, #ctlBodyPane strong, #ctlBodyPane .widgetLabel').forEach((heading) => {
      if (!/parcel information/i.test(norm(heading.textContent))) return;
      let el = heading;
      for (let step = 0; step < 40; step++) {
        el = el.nextElementSibling;
        if (!el) break;
        const tag = el.tagName;
        if ((tag === 'H2' || tag === 'H3') && !/parcel information/i.test(norm(el.textContent))) break;
        PARCEL_LABELS.forEach((labelText) => {
          el.querySelectorAll('strong, b, span, td, th, label, div').forEach((node) => {
            const nodeText = norm(node.textContent).replace(/:$/, '');
            if (nodeText !== labelText) return;
            const val = findValueForLabel(node);
            if (val) addLabelValue(labelText, val);
          });
        });
        if (tag === 'TR' && el.querySelectorAll('td, th').length >= 2) {
          const cells = Array.from(el.querySelectorAll('td, th')).map((c) => norm(c.textContent));
          if (cells[0] && cells[1] && PARCEL_LABELS.includes(cells[0].replace(/:$/, ''))) {
            addLabelValue(cells[0].replace(/:$/, ''), cells[1]);
          }
        }
      }
    });
  };

  extractFromPaneText();
  extractParcelInformationSection();

  PARCEL_LABELS.forEach((labelText) => {
    document.querySelectorAll('#ctlBodyPane span, #ctlBodyPane div, #ctlBodyPane td, #ctlBodyPane th, #ctlBodyPane label, #ctlBodyPane strong').forEach((el) => {
      const text = norm(el.textContent).replace(/:$/, '');
      if (text !== labelText) return;
      const val = findValueForLabel(el);
      if (val) setField(labelText, val);
    });
  });

  const parseTable = (table) => {
    const rows = Array.from(table.querySelectorAll('tr'));
    if (!rows.length) return null;
    const headerCells = rows[0].querySelectorAll('th, td');
    const headers = Array.from(headerCells).map((h) => norm(h.textContent));
    const parsedRows = [];
    for (let i = 1; i < rows.length; i++) {
      const cells = Array.from(rows[i].querySelectorAll('td, th')).map((c) => norm(c.textContent));
      if (!cells.length || cells.every((c) => !c)) continue;
      const rowData = {};
      headers.forEach((header, idx) => {
        if (header && cells[idx]) rowData[header] = cells[idx];
      });
      if (Object.keys(rowData).length) parsedRows.push(rowData);
    }
    return { headers, rows: parsedRows };
  };

  const rowToChainEntry = (row) => {
    const pick = (patterns) => {
      for (const pattern of patterns) {
        for (const [key, val] of Object.entries(row)) {
          if (pattern.test(key) && val) return val;
        }
      }
      return '';
    };
    return {
      document_type: pick([/document type/i, /deed type/i, /deed/i, /sale type/i, /^type$/i]) || 'Sale',
      recording_date: pick([/sale date/i, /sales date/i, /recording date/i, /transfer date/i, /^date$/i]),
      grantor: pick([/grantor/i, /seller/i, /transferor/i, /previous owner/i, /^from$/i]),
      grantee: pick([/grantee/i, /buyer/i, /transferee/i, /new owner/i, /purchaser/i, /^to$/i]),
      book_page: pick([/book\\/page/i, /book page/i, /^book$/i]),
      instrument_number: pick([/instrument/i, /doc #/i, /document number/i, /doc no/i, /recording number/i]),
      sale_price: pick([/sale price/i, /sale amount/i, /price/i, /consideration/i, /amount/i]),
      source: 'sales_information',
      raw_row: row,
    };
  };

  document.querySelectorAll('#ctlBodyPane tr').forEach((row) => {
    const cells = Array.from(row.querySelectorAll('th, td'));
    if (cells.length !== 2) return;
    const key = norm(cells[0].textContent).replace(/:$/, '');
    const val = norm(cells[1].textContent);
    if (!key || !val || key === val) return;
    if (/owner name|tax year|sale date|instrument|grantor|grantee/i.test(key)) return;
    if (cells[0].tagName === 'TH' && cells[1].tagName === 'TH') return;
    setField(key, val);
  });

  document.querySelectorAll('.widgetLabel, th.widgetLabel, span.widgetLabel, td.widgetLabel, label.widgetLabel').forEach((label) => {
    const key = norm(label.textContent).replace(/:$/, '');
    if (!key || /owner type/i.test(key)) return;

    let valEl =
      label.nextElementSibling?.classList?.contains('widgetValue')
        ? label.nextElementSibling
        : label.parentElement?.querySelector('.widgetValue');

    if (!valEl) {
      let sib = label.nextElementSibling;
      while (sib && sib !== label.parentElement) {
        if (sib.classList?.contains('widgetValue') || sib.tagName === 'A') {
          valEl = sib;
          break;
        }
        sib = sib.nextElementSibling;
      }
    }

    if (valEl) {
      const val = norm(valEl.value || valEl.textContent);
      setField(key, val);
    }
  });

  document.querySelectorAll('table').forEach((table) => {
    const parsed = parseTable(table);
    if (!parsed || !parsed.rows.length) return;
    const headerText = parsed.headers.join(' ').toLowerCase();

    if (/owner name/i.test(headerText)) {
      data.owner_rows = parsed.rows;
      const names = parsed.rows
        .map((r) => r['Owner Name'] || r['Owner Names'] || r['Name'] || '')
        .filter((n) => n && !/owner type/i.test(n));
      if (names.length) data['Owner Names'] = [...new Set(names)].join('; ');
      return;
    }

    if (/tax year/i.test(headerText) && /assessed|taxable|exemption/i.test(headerText)) {
      data.assessment_rows = parsed.rows;
      return;
    }

    if (!data.chain_of_title?.length && /sale date|sale price|sales date|document type|grantor|grantee|seller|buyer|deed|instrument|transfer/i.test(headerText)) {
      if (!data.chain_of_title) data.chain_of_title = [];
      parsed.rows.forEach((row) => data.chain_of_title.push(rowToChainEntry(row)));
    }
  });

  const extractSalesInformationSection = () => {
    const chain = [];
    const seenTables = new Set();
    const addTable = (table) => {
      if (!table || seenTables.has(table)) return;
      seenTables.add(table);
      const parsed = parseTable(table);
      if (!parsed?.rows?.length) return;
      const headerText = parsed.headers.join(' ').toLowerCase();
      if (!/sale|instrument|grantor|grantee|deed|transfer|recording/i.test(headerText)) return;
      parsed.rows.forEach((row) => chain.push(rowToChainEntry(row)));
    };

    document.querySelectorAll('#ctlBodyPane h2, #ctlBodyPane h3, #ctlBodyPane .widgetLabel, #ctlBodyPane strong').forEach((heading) => {
      if (!/sales information/i.test(norm(heading.textContent))) return;
      let el = heading;
      for (let step = 0; step < 30; step++) {
        el = el.nextElementSibling;
        if (!el) break;
        const tag = el.tagName;
        if ((tag === 'H2' || tag === 'H3' || tag === 'STRONG') && !/sales information/i.test(norm(el.textContent))) break;
        if (tag === 'TABLE') addTable(el);
        el.querySelectorAll('table').forEach(addTable);
      }
    });
    return chain;
  };

  const salesChain = extractSalesInformationSection();
  if (salesChain.length) {
    data.chain_of_title = salesChain;
  }

  if (data.chain_of_title?.length) {
    const deduped = new Map();
    const score = (entry) => [entry.grantor, entry.grantee, entry.sale_price, entry.instrument_number, entry.book_page].filter(Boolean).length;
    const mergeEntries = (a, b) => ({
      document_type: a.document_type || b.document_type || 'Sale',
      recording_date: a.recording_date || b.recording_date,
      grantor: a.grantor || b.grantor,
      grantee: a.grantee || b.grantee,
      book_page: a.book_page || b.book_page,
      instrument_number: a.instrument_number || b.instrument_number,
      sale_price: a.sale_price || b.sale_price,
      source: a.source || b.source || 'sales_information',
      raw_row: a.raw_row || b.raw_row,
    });
    data.chain_of_title.forEach((entry) => {
      const key = `${entry.recording_date || ''}|${entry.instrument_number || ''}`;
      const existing = deduped.get(key);
      if (!existing || score(entry) > score(existing)) {
        deduped.set(key, existing ? mergeEntries(existing, entry) : entry);
      }
    });
    data.chain_of_title = Array.from(deduped.values());
  }

  document.querySelectorAll('[id*="lblOwnerName"]').forEach((el) => {
    const name = norm(el.textContent);
    if (name && name.length > 2) {
      if (!data.owner_rows) data.owner_rows = [];
      const exists = data.owner_rows.some((r) => (r['Owner Name'] || '') === name);
      if (!exists) data.owner_rows.push({ 'Owner Name': name, 'Owner Type': 'Fee Owner' });
    }
  });

  if (data.owner_rows?.length) {
    const names = data.owner_rows
      .map((r) => r['Owner Name'] || '')
      .filter((n) => n && !/owner type/i.test(n));
    if (names.length) data['Owner Names'] = [...new Set(names)].join('; ');
  }

  data.source_url = window.location.href;
  const kv = window.location.href.match(/KeyValue=([^&]+)/i);
  if (kv) data.key_value = decodeURIComponent(kv[1]);

  return data;
}
"""

HEADER_LABELS = frozenset(
    {
        "owner name",
        "owner type",
        "owner names",
        "tax year",
        "property class",
        "sale date",
        "document type",
    }
)


def _is_header_value(val: str) -> bool:
    return val.strip().lower() in HEADER_LABELS


def _owners_from_rows(owner_rows: list[dict[str, Any]]) -> Optional[str]:
    names: list[str] = []
    for row in owner_rows:
        if not isinstance(row, dict):
            continue
        name = row.get("Owner Name") or row.get("Owner Names") or row.get("Name")
        if name and not _is_header_value(str(name)):
            names.append(str(name).strip())
    if names:
        return "; ".join(dict.fromkeys(names))
    return None


def _pick_row_value(row: dict[str, Any], *patterns: str) -> Optional[str]:
    for pattern in patterns:
        pat = re.compile(pattern, re.I)
        for key, val in row.items():
            if val and pat.search(str(key)):
                return str(val).strip()
    return None


def _normalize_chain_entry(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "document_type": (
            _pick_row_value(row, r"document type", r"deed type", r"deed", r"sale type", r"^type$")
            or row.get("document_type")
            or "Sale"
        ),
        "recording_date": (
            _pick_row_value(row, r"sale date", r"sales date", r"recording date", r"transfer date", r"^date$")
            or row.get("recording_date")
        ),
        "grantor": (
            _pick_row_value(row, r"grantor", r"seller", r"transferor", r"previous owner", r"^from$")
            or row.get("grantor")
        ),
        "grantee": (
            _pick_row_value(row, r"grantee", r"buyer", r"transferee", r"new owner", r"purchaser", r"^to$")
            or row.get("grantee")
        ),
        "book_page": (
            _pick_row_value(row, r"book/page", r"book page", r"^book$") or row.get("book_page")
        ),
        "instrument_number": (
            _pick_row_value(row, r"instrument", r"doc #", r"document number", r"doc no", r"recording number")
            or row.get("instrument_number")
        ),
        "sale_price": (
            _pick_row_value(row, r"sale price", r"sale amount", r"price", r"consideration", r"amount")
            or row.get("sale_price")
        ),
        "source": row.get("source") or "sales_information",
        "raw_row": row.get("raw_row") or {
            k: v for k, v in row.items() if k not in ("document_type", "recording_date", "grantor", "grantee")
        },
    }


def _merge_chain_entries(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    merged = {**a}
    for key, value in b.items():
        if value and not merged.get(key):
            merged[key] = value
    return merged


def _chain_entry_score(entry: dict[str, Any]) -> int:
    return sum(
        1
        for key in ("grantor", "grantee", "sale_price", "instrument_number", "book_page", "document_type")
        if entry.get(key)
    )


def _parse_sales_table(table: Any, data: dict[str, Any]) -> None:
    rows = table.select("tr")
    if not rows:
        return
    headers = [_clean(c.get_text()) for c in rows[0].select("th, td")]
    if not headers:
        return
    header_text = " ".join(h or "" for h in headers).lower()
    if not re.search(r"sale|instrument|grantor|grantee|deed|transfer|recording", header_text, re.I):
        return

    chain = data.setdefault("chain_of_title", [])
    for row in rows[1:]:
        cells = [_clean(c.get_text()) for c in row.select("td, th")]
        if not cells or not any(cells):
            continue
        row_data = {
            headers[i]: cells[i]
            for i in range(min(len(headers), len(cells)))
            if headers[i] and cells[i]
        }
        if row_data:
            chain.append(_normalize_chain_entry(row_data))


def _parse_sales_information_section(soup: BeautifulSoup, data: dict[str, Any]) -> None:
    for heading in soup.select("#ctlBodyPane h2, #ctlBodyPane h3, #ctlBodyPane .widgetLabel, #ctlBodyPane strong"):
        text = _clean(heading.get_text())
        if not text or not re.search(r"sales information", text, re.I):
            continue
        for sibling in heading.next_siblings:
            if getattr(sibling, "name", None) in ("h2", "h3", "strong"):
                break
            if getattr(sibling, "name", None) == "table":
                _parse_sales_table(sibling, data)
            if hasattr(sibling, "select"):
                for table in sibling.select("table"):
                    _parse_sales_table(table, data)


def _parse_html_tables(soup: BeautifulSoup, data: dict[str, Any]) -> None:
    for table in soup.select("table"):
        rows = table.select("tr")
        if not rows:
            continue
        headers = [_clean(c.get_text()) for c in rows[0].select("th, td")]
        if not headers:
            continue
        header_text = " ".join(h or "" for h in headers).lower()
        parsed_rows: list[dict[str, str]] = []

        for row in rows[1:]:
            cells = [_clean(c.get_text()) for c in row.select("td, th")]
            if not cells or not any(cells):
                continue
            row_data = {
                headers[i]: cells[i]
                for i in range(min(len(headers), len(cells)))
                if headers[i] and cells[i]
            }
            if row_data:
                parsed_rows.append(row_data)

        if not parsed_rows:
            continue

        if "owner name" in header_text:
            data["owner_rows"] = parsed_rows
            owners = _owners_from_rows(parsed_rows)
            if owners:
                data["Owner Names"] = owners
        elif "tax year" in header_text and re.search(r"assessed|taxable|exemption", header_text, re.I):
            data["assessment_rows"] = parsed_rows
        elif not data.get("chain_of_title") and re.search(
            r"sale date|sale price|document type|grantor|grantee|seller|buyer|instrument|transfer",
            header_text,
            re.I,
        ):
            chain = data.setdefault("chain_of_title", [])
            for row in parsed_rows:
                chain.append(_normalize_chain_entry(row))


PARCEL_INFO_KEYS = frozenset(
    {
        "parcel number",
        "location address",
        "project name",
        "legal information",
        "legal description",
        "property class",
        "land area (acres)",
        "land area",
    }
)


def _key(data: dict[str, Any], *names: str) -> Optional[str]:
    lowered = {
        str(k).lower(): v
        for k, v in data.items()
        if k not in ("assessment_rows", "owner_rows", "chain_of_title")
    }
    for name in names:
        val = lowered.get(name.lower())
        if val and not _is_header_value(str(val)):
            return str(val)
    return None


def parcel_record_from_schneider_data(
    data: dict[str, Any],
    source_url: Optional[str] = None,
) -> ParcelRecord:
    if source_url:
        data = {**data, "source_url": source_url}

    owner_rows = data.get("owner_rows")
    owners = None
    if isinstance(owner_rows, list):
        owners = _owners_from_rows(owner_rows)

    if not owners:
        owners = _key(
            data,
            "owner names",
            "owner names(s)",
            "owner name",
            "owner",
            "owner(s)",
        )

    apn = _key(
        data,
        "parcel number",
        "parcel id",
        "parcel #",
        "tmk",
        "apn",
        "pin",
        "key_value",
    )
    address = _key(
        data,
        "location address",
        "property address",
        "situs address",
        "address",
        "location",
    )
    legal = _key(
        data,
        "legal information",
        "legal description",
        "legal",
        "project name",
    )
    assessed_text = _key(
        data,
        "total property assessed value",
        "total net taxable value",
        "assessed value",
        "total value",
        "market value",
    )

    assessment_rows = data.get("assessment_rows")
    if isinstance(assessment_rows, list) and assessment_rows and not assessed_text:
        latest = assessment_rows[0]
        if isinstance(latest, dict):
            assessed_text = (
                latest.get("Total Property Assessed Value")
                or latest.get("Total Net Taxable Value")
                or latest.get("Assessed Value")
            )

    chain = data.get("chain_of_title")
    if isinstance(chain, list):
        deduped: dict[str, dict[str, Any]] = {}
        for entry in chain:
            if not isinstance(entry, dict):
                continue
            normalized_entry = _normalize_chain_entry(entry)
            key = f"{normalized_entry.get('recording_date')}|{normalized_entry.get('instrument_number')}"
            existing = deduped.get(key)
            if not existing or _chain_entry_score(normalized_entry) > _chain_entry_score(existing):
                deduped[key] = _merge_chain_entries(existing, normalized_entry) if existing else normalized_entry
        data["chain_of_title"] = list(deduped.values())

    normalized: dict[str, Any] = {}
    for key, value in data.items():
        if key in ("assessment_rows", "owner_rows", "chain_of_title"):
            normalized[key] = value
            continue
        if isinstance(value, str):
            if _is_header_value(value) and key.lower() in ("owner name", "owner names"):
                continue
            normalized[key.lower()] = value
        else:
            normalized[key] = value

    if not address:
        address = normalized.get("location address") or normalized.get("property address")
    if not legal:
        legal = normalized.get("legal information") or normalized.get("legal description")

    return ParcelRecord(
        apn=apn or normalized.get("parcel number"),
        owner_name=owners,
        legal_desc=legal,
        assessed_value=_parse_value(assessed_text),
        property_address=address,
        source="assessor",
        raw_json=normalized,
    )


PARCEL_LABEL_NAMES = frozenset(
    {
        "Parcel Number",
        "Location Address",
        "Project Name",
        "Legal Information",
        "Property Class",
        "Land Area (Acres)",
        "Land Area",
    }
)


def _extract_from_pane_text(soup: BeautifulSoup, data: dict[str, Any]) -> None:
    pane = soup.select_one("#ctlBodyPane")
    if not pane:
        return
    text = pane.get_text("\n")
    patterns = [
        ("Parcel Number", r"Parcel Number\s*\n\s*([^\n]+)"),
        ("Location Address", r"Location Address\s*\n\s*([^\n]+)"),
        ("Project Name", r"Project Name\s*\n\s*([^\n]+)"),
        ("Legal Information", r"Legal Information\s*\n\s*([\s\S]+?)\n\s*Property Class"),
        ("Property Class", r"Property Class\s*\n\s*([^\n]+)"),
        ("Land Area (Acres)", r"Land Area \(Acres\)\s*\n\s*([^\n]+)"),
    ]
    for label, pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            val = _clean(match.group(1))
            if val and val != label:
                data[label] = val


def _extract_value_after_label(label_el: Any) -> Optional[str]:
    sibling = label_el.find_next_sibling()
    if sibling:
        val = _clean(sibling.get_text())
        if val and val != _clean(label_el.get_text()):
            return val
    parent = label_el.parent
    if parent:
        parent_sibling = parent.find_next_sibling()
        if parent_sibling:
            val = _clean(parent_sibling.get_text())
            if val:
                return val
    row = label_el.find_parent("tr")
    if row:
        cells = row.find_all(["td", "th"])
        if len(cells) >= 2:
            return _clean(cells[1].get_text())
    return None


def _parse_parcel_information_section(soup: BeautifulSoup, data: dict[str, Any]) -> None:
    label_names_lower = {name.lower() for name in PARCEL_LABEL_NAMES}

    for el in soup.select('#ctlBodyPane [id*="lbl"]'):
        el_id = (el.get("id") or "").lower()
        val = _clean(el.get_text())
        if not val or val.lower() in label_names_lower or _is_header_value(val):
            continue
        if "widgetLabel" in (el.get("class") or []):
            continue
        if "parcelid" in el_id or ("parcel" in el_id and "map" not in el_id):
            data["Parcel Number"] = val
        elif any(token in el_id for token in ("locationaddress", "situsaddress", "situs")):
            data["Location Address"] = val
        elif any(token in el_id for token in ("legalinformation", "legaldescription", "legaldesc")):
            data["Legal Information"] = val
        elif "projectname" in el_id or "project" in el_id:
            data["Project Name"] = val
        elif "propertyclass" in el_id:
            data["Property Class"] = val

    for heading in soup.select("#ctlBodyPane h2, #ctlBodyPane h3, #ctlBodyPane strong, #ctlBodyPane .widgetLabel"):
        text = _clean(heading.get_text())
        if not text or not re.search(r"parcel information", text, re.I):
            continue
        for sibling in heading.next_siblings:
            if getattr(sibling, "name", None) in ("h2", "h3"):
                break
            if not hasattr(sibling, "select"):
                continue
            for node in sibling.select("strong, b, span, td, th, label"):
                label = _clean(node.get_text())
                if not label or label.rstrip(":") not in PARCEL_LABEL_NAMES:
                    continue
                val = _extract_value_after_label(node)
                if val:
                    data[label.rstrip(":")] = val


def _extract_id_fields(soup: BeautifulSoup, data: dict[str, Any]) -> None:
    _parse_parcel_information_section(soup, data)


def extract_schneider_qpublic_from_html(html: str, page_url: Optional[str] = None) -> ParcelRecord:
    soup = BeautifulSoup(html, "lxml")
    data: dict[str, Any] = {}

    _extract_id_fields(soup, data)
    _extract_from_pane_text(soup, data)

    for label in soup.select(".widgetLabel, th.widgetLabel, span.widgetLabel, td.widgetLabel"):
        key = _clean(label.get_text())
        if not key or _is_header_value(key):
            continue
        key = key.rstrip(":")

        val_el = label.find_next(class_="widgetValue")
        if not val_el:
            sibling = label.find_next_sibling()
            if sibling and sibling.name in ("span", "td", "div", "a"):
                val_el = sibling

        if val_el:
            val = _clean(val_el.get("value") or val_el.get_text())
            if val and val.lower() != key.lower() and not _is_header_value(val):
                data[key] = val

    for row in soup.select("#ctlBodyPane tr"):
        cells = row.find_all(["th", "td"])
        if len(cells) != 2:
            continue
        key = _clean(cells[0].get_text())
        val = _clean(cells[1].get_text())
        if not key or not val or key == val:
            continue
        key = key.rstrip(":")
        if re.search(r"owner name|tax year|sale date|instrument|grantor|grantee", key, re.I):
            continue
        if cells[0].name == "th" and cells[1].name == "th":
            continue
        data[key] = val

    _parse_sales_information_section(soup, data)
    _parse_html_tables(soup, data)

    owner_els = soup.select('[id*="lblOwnerName"]')
    if owner_els:
        owner_rows = data.setdefault("owner_rows", [])
        for el in owner_els:
            name = _clean(el.get_text())
            if name and not _is_header_value(name):
                owner_rows.append({"Owner Name": name, "Owner Type": "Fee Owner"})
        owners = _owners_from_rows(owner_rows)
        if owners:
            data["Owner Names"] = owners

    if page_url:
        data["source_url"] = page_url
        match = re.search(r"KeyValue=([^&]+)", page_url, re.I)
        if match:
            data["key_value"] = match.group(1)

    return parcel_record_from_schneider_data(data, source_url=page_url)
