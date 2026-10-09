"""Extract, expand, and normalize Miami-Dade recorder party names for title reports."""
from __future__ import annotations

import re
from typing import Any

from app.extraction.book_page import parse_book_page

_ET_AL_RE = re.compile(r"\s+ET\s+AL\.?$", re.I)
_NOISE_RE = re.compile(
    r"^(party name|party type|direct|reverse|parties|sources?)$",
    re.I,
)
_ENTITY_MARKERS = re.compile(
    r"\b(LTD|LLC|INC|CORP|CORPORATION|CO|COMPANY|BANK|DEV|DEVELOPMENT|"
    r"SUBDIVISION|SUBD|ASSOCIATION|ASSN|NA|N\.A\.|TRUST|ESTATE|MORTGAGE|"
    r"FUND|HOLDINGS|GROUP|PARTNERS|LP|LLP|LIMITED|INVESTMENTS)\b",
    re.I,
)
_ENTITY_SUFFIX_RE = re.compile(
    r"\b(A FLORIDA CORPORATION|FLORIDA CORPORATION|A FL CORP|LIMITED LIABILITY COMPANY|"
    r"LIMITED PARTNERSHIP|LIMITED LIABILITY PARTNERSHIP|NATIONAL ASSOCIATION|"
    r"CORPORATION|CORPORATE|CORP|COMPANY|CO|LLC|LLP|LP|LTD|INC)\b",
    re.I,
)
_FIRST_NAME_NICKNAMES: dict[str, list[str]] = {
    "PHILIP": ["PHIL", "FELIPE", "PIP", "PHILIPPA"],
    "PHILLIP": ["PHIL", "FELIPE", "PIP", "PHILIPPA"],
    "WILLIAM": ["WILL", "BILL", "BILLY"],
    "ROBERT": ["ROB", "BOB", "BOBBY"],
    "JOSEPH": ["JOE", "JOSE"],
    "JAMES": ["JIM", "JIMMY", "JAMEY"],
    "MICHAEL": ["MIKE", "MIGUEL"],
    "RICHARD": ["RICH", "RICK", "DICK"],
    "THOMAS": ["TOM", "TOMMY"],
    "ELIZABETH": ["LIZ", "BETH", "BETTY"],
    "JENNIFER": ["JEN", "JENNY"],
    "CHRISTOPHER": ["CHRIS"],
    "ANTHONY": ["TONY"],
    "FRANCISCO": ["FRANK", "PACO"],
    "AURELIO": ["AURELIUS"],
}


def normalize_party_name(raw: str) -> str:
    """Normalize a party name for display in Name Searches."""
    name = re.sub(r"\s+", " ", str(raw or "").strip())
    name = _ET_AL_RE.sub("", name).strip(" ,;/")
    return name.upper()


_ENTITY_SUFFIX_TOKENS = {
    "INC",
    "LLC",
    "LTD",
    "CORP",
    "CO",
    "LP",
    "LLP",
    "CORPORATION",
    "COMPANY",
}


def sanitize_miami_dade_party_name_for_search(raw: str) -> str:
    """Prepare a party name for Miami-Dade Name/Document search entry."""
    name = re.sub(r"\s+", " ", str(raw or "").strip())
    name = _ET_AL_RE.sub("", name).strip(" ,;/")
    if not name:
        return ""
    name = name.upper()

    if "," in name:
        left, right = [part.strip() for part in name.split(",", 1)]
        if left and right:
            left_token = left.split()[0] if left.split() else left
            right_token = right.split()[-1] if right.split() else right
            if left_token in _ENTITY_SUFFIX_TOKENS:
                name = f"{right} {left}".strip()
            elif right_token in _ENTITY_SUFFIX_TOKENS:
                name = f"{left} {right}".strip()
            else:
                name = f"{left} {right}".strip()

    name = re.sub(r"[,;/]", " ", name)
    name = re.sub(r"[^\w\s#&]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name.upper()


def split_party_name_phrase(raw: str) -> list[str]:
    """Split composite party strings such as 'A / B' or 'A, B'."""
    if not raw:
        return []
    parts = re.split(
        r"[/;\n]+|,(?!\s*(?:N\.?\s*A\.?|INC\.?|LTD\.?|LLC\.?|CORP\.?|CO\.?)\b)",
        str(raw),
        flags=re.I,
    )
    names: list[str] = []
    for part in parts:
        normalized = normalize_party_name(part)
        if normalized and not _NOISE_RE.match(normalized):
            names.append(normalized)
    return names


def collect_party_names_from_metadata(metadata: dict[str, Any]) -> list[str]:
    """Collect party names already present on scraped recorder metadata."""
    names: list[str] = []
    for key in ("party_name", "grantor", "grantee"):
        names.extend(split_party_name_phrase(str(metadata.get(key) or "")))
    for key in ("party_names", "name_search_names"):
        value = metadata.get(key)
        if isinstance(value, list):
            for item in value:
                names.extend(split_party_name_phrase(str(item)))
        elif value:
            names.extend(split_party_name_phrase(str(value)))
    return dedupe_party_names(names)


def dedupe_party_names(names: list[str]) -> list[str]:
    """Return unique party names in first-seen order."""
    seen: set[str] = set()
    result: list[str] = []
    for raw in names:
        name = normalize_party_name(raw)
        if not name or name in seen or _NOISE_RE.match(name):
            continue
        seen.add(name)
        result.append(name)
    return result


def _is_entity_name(name: str) -> bool:
    return bool(_ENTITY_MARKERS.search(name)) or "#" in name or "&" in name


def _strip_entity_suffixes(name: str) -> str:
    cleaned = _ENTITY_SUFFIX_RE.sub(" ", name)
    return re.sub(r"\s+", " ", cleaned).strip()


def _party_match_key(name: str) -> str:
    key = _strip_entity_suffixes(normalize_party_name(name))
    return re.sub(r"[^\w]+", "", key)


def _party_names_refer_to_same_entity(left: str, right: str) -> bool:
    left_key = _party_match_key(left)
    right_key = _party_match_key(right)
    if not left_key or not right_key:
        return False
    return left_key == right_key or left_key in right_key or right_key in left_key


def _expand_individual_name_variations(name: str) -> list[str]:
    tokens = name.split()
    if len(tokens) < 2:
        return [name]

    variations: list[str] = [name]
    last = tokens[0]
    first = tokens[1]
    rest = tokens[2:]

    def add(value: str) -> None:
        normalized = normalize_party_name(value)
        if normalized and not _NOISE_RE.match(normalized):
            variations.append(normalized)

    add(f"{last} {first}")
    if len(first) >= 3:
        add(f"{last} {first[:3]}")
    if len(first) >= 4:
        add(f"{last} {first[:4]}")

    if rest:
        middle = rest[0]
        if len(middle) == 1:
            add(f"{last} {middle}")
            add(f"{last} {first} {middle}")
        else:
            add(f"{last} {middle}")
            add(f"{last} {first} {middle[0]}")
            add(f"{last} {first} {middle}")
    elif len(first) >= 5:
        add(f"{last} {first[0]}")

    for nick in _FIRST_NAME_NICKNAMES.get(first, []):
        add(f"{last} {nick}")
        if rest and len(rest[0]) == 1:
            add(f"{last} {nick} {rest[0]}")

    if first in ("PHILIP", "PHILLIP"):
        add(f"{last} PHILIP A")

    if len(tokens) >= 3 and len(tokens[-1]) == 1:
        add(f"{last} {tokens[-1]}")
        add(f"{last} {first}")

    return dedupe_party_names(variations)


def _expand_entity_name_variations(name: str) -> list[str]:
    variations: list[str] = [name]

    def add(value: str) -> None:
        normalized = normalize_party_name(value)
        if normalized and not _NOISE_RE.match(normalized):
            variations.append(normalized)

    if re.search(r"\bDEV\b", name, re.I):
        add(re.sub(r"\bDEV\b", "DEVELOPMENT", name, flags=re.I))
        without_number = re.sub(r"\s*#\d+\s*", " ", name)
        add(re.sub(r"\bDEV\b", "DEVELOPMENT", without_number, flags=re.I))
        company = re.sub(r"\s*#\d+\s*", " ", name, flags=re.I)
        company = re.sub(r"\bDEV\b", "DEVELOPMENT", company, flags=re.I)
        company = re.sub(r"\s+LTD\.?\s*$", "", company, flags=re.I).strip()
        add(f"{company} COMPANY")

    if re.search(r"\bSUBD\b", name, re.I):
        add(re.sub(r"\bSUBD\b\.?", "SUBDIVISION", name, flags=re.I))
    if re.search(r"\bSUBDIVISION\b", name, re.I):
        add(re.sub(r"\s+SUBDIVISION\b", "", name, flags=re.I))
        add(re.sub(r"\s+SUBDIVISION\b", " SUBD", name, flags=re.I))

    if "BANK" in name.upper():
        no_punct = re.sub(r"[.,]", "", name)
        add(no_punct)
        add(re.sub(r"\s+", " ", no_punct.replace(" NA", " N A")))
        base = re.sub(r",?\s*N\.?\s*A\.?\s*", " ", name, flags=re.I)
        base = re.sub(r"\s+", " ", base).strip()
        add(base)
        add(f"{base} NATIONAL ASSOCIATION")

    if re.search(r"\bCO\b", name, re.I) and "COMPANY" not in name.upper():
        add(re.sub(r"\bCO\b", "COMPANY", name, flags=re.I))

    add(re.sub(r"[.,]", "", name))
    add(re.sub(r"\s+", " ", re.sub(r"[.,]", " ", name)))

    stripped = _strip_entity_suffixes(name)
    if stripped and stripped != name:
        add(stripped)

    return dedupe_party_names(variations)


def _expand_compound_surname_variations(name: str) -> list[str]:
    """Generate hyphenated/joined/split surname searches (e.g. CORTES RIOS JUAN C)."""
    normalized = normalize_party_name(name)
    tokens = normalized.split()
    if len(tokens) < 3 or _is_entity_name(normalized):
        return []

    variations: list[str] = []

    def add(value: str) -> None:
        cleaned = normalize_party_name(value)
        if cleaned and not _NOISE_RE.match(cleaned):
            variations.append(cleaned)

    if len(tokens) >= 4:
        compound = " ".join(tokens[:2])
        remainder = " ".join(tokens[2:])
        add(f"{compound} {remainder}")
        add(f"{compound.replace(' ', '-')} {remainder}")
        add(f"{compound.replace(' ', '')} {remainder}")
        add(f"{tokens[0]} {remainder}")
        add(f"{tokens[1]} {remainder}")
    elif len(tokens) == 3:
        compound = f"{tokens[0]} {tokens[1]}"
        first = tokens[2]
        add(compound)
        add(compound.replace(" ", "-"))
        add(compound.replace(" ", ""))
        add(f"{tokens[0]} {first}")
        add(f"{tokens[1]} {first}")

    return dedupe_party_names(variations)


def expand_name_search_variations(name: str) -> list[str]:
    """Generate recorder name-search permutations for a single party name."""
    normalized = normalize_party_name(name)
    if not normalized:
        return []
    if _is_entity_name(normalized):
        return _expand_entity_name_variations(normalized)
    variations = _expand_individual_name_variations(normalized)
    variations.extend(_expand_compound_surname_variations(normalized))
    return dedupe_party_names(variations)


def dedupe_equivalent_party_names(names: list[str]) -> list[str]:
    """Collapse entity aliases such as 'MIAMI EDGE INVESTMENTS' and 'MIAMI EDGE INVESTMENTS INC'."""
    seen: set[str] = set()
    result: list[str] = []
    for raw in names:
        normalized = normalize_party_name(raw)
        if not normalized:
            continue
        key = _party_match_key(normalized)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result


def build_names_to_search(base_names: list[str], *, expand_variations: bool = True) -> list[str]:
    """Expand base party names into the full recorder search queue."""
    base_names = dedupe_equivalent_party_names(base_names)
    if not expand_variations:
        return dedupe_party_names(base_names)

    expanded: list[str] = []
    for base_name in base_names:
        normalized = normalize_party_name(base_name)
        if not normalized:
            continue
        expanded.append(normalized)
        expanded.extend(expand_name_search_variations(normalized))
    return dedupe_equivalent_party_names(expanded)


def build_name_search_queue(
    base_names: list[str],
    *,
    expand_variations: bool = True,
) -> list[tuple[str, bool]]:
    """Return party names to search with a flag for generated variations."""
    base_names = dedupe_equivalent_party_names(base_names)
    if not expand_variations:
        return [(name, False) for name in dedupe_party_names(base_names)]

    queued: list[tuple[str, bool]] = []
    seen_entity_keys: set[str] = set()
    seen_labels: set[str] = set()
    for base_name in base_names:
        normalized = normalize_party_name(base_name)
        if not normalized:
            continue
        if normalized not in seen_labels:
            seen_labels.add(normalized)
            queued.append((normalized, False))
            entity_key = _party_match_key(normalized)
            if entity_key:
                seen_entity_keys.add(entity_key)
        for variant in expand_name_search_variations(normalized):
            variant_name = normalize_party_name(variant)
            if not variant_name or variant_name == normalized:
                continue
            if variant_name in seen_labels:
                continue
            seen_labels.add(variant_name)
            queued.append((variant_name, True))
    return queued


def _subdivision_name_variations(raw: str) -> list[str]:
    name = normalize_party_name(raw)
    if not name:
        return []
    variations = [name]
    expanded = name
    if re.search(r"\bPL\b", name):
        expanded = normalize_party_name(re.sub(r"\bPL\b", "PLACE", name))
        variations.append(expanded)
    base = expanded
    if "PLACE" in base and "SUBDIVISION" not in base:
        variations.append(f"{base} SUBDIVISION")
        variations.append(f"{base} SUBD")
    return dedupe_party_names(variations)


def _document_source_label(doc: dict[str, Any]) -> str:
    ocr = doc.get("ocr_json") or {}
    if ocr.get("book_number") and ocr.get("page_number"):
        return f"{ocr['book_number']}/{ocr['page_number']}"
    source_bits = [
        str(doc.get("book_page") or "").strip(),
        str(doc.get("instrument_number") or "").strip(),
    ]
    return next((bit for bit in source_bits if bit), "Recorder")


def is_entity_party_name(name: str) -> bool:
    """Return True when a party name looks like a company/entity rather than a person."""
    return _is_entity_name(name)


def is_base_name_for_search(name: str, base_names: list[str]) -> bool:
    """Return True when a queued name is an original/base party name (not a generated variation)."""
    normalized = sanitize_miami_dade_party_name_for_search(name)
    if not normalized:
        return False
    base_normalized = {
        sanitize_miami_dade_party_name_for_search(base)
        for base in base_names
        if sanitize_miami_dade_party_name_for_search(base)
    }
    return normalized in base_normalized


def should_apply_address_filter_for_name_search(
    name: str,
    *,
    property_address: str,
    is_name_variation: bool = False,
) -> bool:
    """Address filter applies only to individual name variations, not base names or companies."""
    if not property_address.strip():
        return False
    if is_entity_party_name(name):
        return False
    return is_name_variation


def parse_miami_dade_party_name_fields(name: str) -> dict[str, str]:
    """Split a normalized recorder party name into Miami-Dade form fields."""
    normalized = sanitize_miami_dade_party_name_for_search(name)
    if not normalized:
        return {"kind": "unknown"}

    if is_entity_party_name(normalized):
        return {"kind": "company", "company_name": normalized, "full_name": normalized}

    tokens = normalized.split()
    if len(tokens) >= 2:
        last_name = tokens[0]
        # "MORALES A" is a last-name + middle-initial search, not first name "A".
        if len(tokens) == 2 and len(tokens[1]) == 1:
            return {
                "kind": "person",
                "last_name": last_name,
                "first_name": "",
                "middle_name": tokens[1],
                "full_name": normalized,
            }
        first_name = tokens[1]
        middle_name = " ".join(tokens[2:]) if len(tokens) > 2 else ""
        return {
            "kind": "person",
            "last_name": last_name,
            "first_name": first_name,
            "middle_name": middle_name,
            "full_name": normalized,
        }

    if len(tokens) == 1:
        return {
            "kind": "person",
            "last_name": tokens[0],
            "first_name": "",
            "middle_name": "",
            "full_name": normalized,
        }

    return {"kind": "company", "company_name": normalized, "full_name": normalized}


def collect_base_name_sources(
    documents: list[dict[str, Any]],
    *,
    property_record: dict[str, Any] | None = None,
    chain_of_title: list[dict[str, Any]] | None = None,
) -> list[tuple[str, str]]:
    """Collect raw party names and the source label they came from."""
    pairs: list[tuple[str, str]] = []

    for doc in documents:
        if not isinstance(doc, dict):
            continue
        ocr = doc.get("ocr_json") or {}
        if ocr.get("source") in ("assessor_sales", "ai_agent", "chatbot", "gis"):
            continue
        if doc.get("document_type") in ("AI Title Analysis", "AI Chatbot Response", "gis_map"):
            continue

        source = _document_source_label(doc)
        for name in collect_party_names_from_metadata({**ocr, **doc}):
            pairs.append((name, source))

    for entry in chain_of_title or []:
        if not isinstance(entry, dict):
            continue
        source = str(entry.get("book_page") or "Chain").strip() or "Chain"
        for key in ("grantor", "grantee"):
            for name in split_party_name_phrase(str(entry.get(key) or "")):
                pairs.append((name, source))

    if property_record:
        for name in split_party_name_phrase(str(property_record.get("owner_name") or "")):
            pairs.append((name, "Assessor"))
        raw = property_record.get("raw_json") or {}
        for key in ("subdivision", "subdivision_name"):
            for variant in _subdivision_name_variations(str(raw.get(key) or "")):
                pairs.append((variant, "Assessor"))

    return pairs


def collect_recorder_party_names_for_search(
    documents: list[dict[str, Any]],
) -> list[str]:
    """Collect unique party names from recorder documents for follow-up name searches."""
    names: list[str] = []
    for base_name, _source in collect_base_name_sources(documents):
        names.append(base_name)
    return dedupe_party_names(names)


def collect_current_owner_names_for_search(
    *,
    property_record: dict[str, Any] | None = None,
    ctx_owner_name: str | None = None,
    input_owner_name: str | None = None,
) -> list[str]:
    """Collect only the current owner-of-record name(s) for Current Search name lookups."""
    names: list[str] = []
    for raw in (input_owner_name, ctx_owner_name):
        names.extend(split_party_name_phrase(str(raw or "")))

    if property_record:
        names.extend(split_party_name_phrase(str(property_record.get("owner_name") or "")))
        raw_json = property_record.get("raw_json") or {}
        for row in raw_json.get("owner_rows") or []:
            if not isinstance(row, dict):
                continue
            for key in ("Owner Name", "owner_name", "name", "Owner"):
                if row.get(key):
                    names.extend(split_party_name_phrase(str(row[key])))
                    break

    return dedupe_party_names(names)


def collect_related_individual_names_from_documents(
    documents: list[dict[str, Any]],
    anchor_names: list[str],
) -> list[str]:
    """Collect individual party names from recorder documents tied to the current owner."""
    if not anchor_names:
        return []

    individuals: list[str] = []
    for doc in documents:
        if not isinstance(doc, dict):
            continue
        ocr = doc.get("ocr_json") or {}
        if ocr.get("source") in ("assessor_sales", "assessor", "tax_bill", "gis"):
            continue
        if doc.get("document_type") in ("AI Title Analysis", "AI Chatbot Response", "gis_map"):
            continue

        metadata = {**ocr, **doc}
        parties = collect_party_names_from_metadata(metadata)
        if not any(
            _party_names_refer_to_same_entity(party, anchor)
            for party in parties
            for anchor in anchor_names
        ):
            continue

        for party in parties:
            if party and not is_entity_party_name(party):
                individuals.append(party)

    return dedupe_party_names(individuals)


def collect_current_owner_search_names(
    *,
    property_record: dict[str, Any] | None = None,
    ctx_owner_name: str | None = None,
    input_owner_name: str | None = None,
    documents: list[dict[str, Any]] | None = None,
    chain_of_title: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Collect current owner and related individual parties for Current Search name lookups."""
    names = collect_current_owner_names_for_search(
        property_record=property_record,
        ctx_owner_name=ctx_owner_name,
        input_owner_name=input_owner_name,
    )
    names.extend(
        collect_related_individual_names_from_documents(documents or [], names)
    )

    for entry in chain_of_title or []:
        if not isinstance(entry, dict):
            continue
        for key in ("grantor", "grantee"):
            names.extend(split_party_name_phrase(str(entry.get(key) or "")))

    return dedupe_party_names(names)


def build_name_search_entries(
    documents: list[dict[str, Any]],
    *,
    property_record: dict[str, Any] | None = None,
    chain_of_title: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    """Aggregate expanded Name Searches rows for the title report."""
    entries_by_name: dict[str, dict[str, str]] = {}

    for base_name, source in collect_base_name_sources(
        documents,
        property_record=property_record,
        chain_of_title=chain_of_title,
    ):
        for variant in expand_name_search_variations(base_name):
            existing = entries_by_name.get(variant)
            if existing:
                if source and source not in existing["source"]:
                    existing["source"] = f"{existing['source']}, {source}"
                continue
            entries_by_name[variant] = {"name": variant, "source": source}

    entries = list(entries_by_name.values())
    entries.sort(key=lambda row: row["name"])
    return entries


def build_name_searcher_report_entries(
    documents: list[dict[str, Any]],
    searched_names: list[str],
) -> list[dict[str, str]]:
    """Build report rows for names actually searched by the Name Searcher node."""
    source_by_name: dict[str, str] = {}
    for base_name, source in collect_base_name_sources(documents):
        source_by_name.setdefault(base_name, source)
        for variant in expand_name_search_variations(base_name):
            source_by_name.setdefault(variant, source)

    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw_name in searched_names:
        name = normalize_party_name(raw_name)
        if not name or name in seen:
            continue
        seen.add(name)
        entries.append(
            {
                "name": name,
                "source": source_by_name.get(name, "Recorder"),
            }
        )
    return entries


def is_book_page_label(raw: str) -> bool:
    """Return True when a value looks like a recorder book/page label, not a party name."""
    return parse_book_page(str(raw or "").strip()) is not None


def is_recorder_report_document(doc: dict[str, Any]) -> bool:
    """Return True when a document belongs to recorder/name-search, not assessor or AI."""
    if not isinstance(doc, dict):
        return False
    ocr = doc.get("ocr_json") or {}
    if not isinstance(ocr, dict):
        ocr = {}
    source = str(ocr.get("source") or ocr.get("storage_category") or "").strip().lower()
    if source in ("assessor", "assessor_sales", "ai_agent", "chatbot", "gis"):
        return False
    if doc.get("document_type") in ("AI Title Analysis", "AI Chatbot Response", "gis_map"):
        return False
    folder = str(doc.get("folder_name") or ocr.get("folder_name") or "").lower()
    if folder.startswith("assessor"):
        return False
    if source in ("recorder", "name_searcher"):
        return True
    if folder.startswith("recorder_") or folder.startswith("name_search"):
        return True
    if ocr.get("book_number") and ocr.get("page_number"):
        return True
    if doc.get("book_page"):
        return True
    return False


def group_documents_by_name_search(
    documents: list[dict[str, Any]],
    name_searches: list[dict[str, str]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split documents into name-search groups and primary recorder documents."""
    order: list[str] = []
    if name_searches:
        for entry in name_searches:
            if not isinstance(entry, dict):
                continue
            name = normalize_party_name(str(entry.get("name") or ""))
            if name and name not in order:
                order.append(name)

    groups: dict[str, list[dict[str, Any]]] = {}
    primary: list[dict[str, Any]] = []

    for doc in documents:
        if not isinstance(doc, dict):
            continue
        if not is_recorder_report_document(doc):
            continue
        ocr = doc.get("ocr_json") or {}
        if not isinstance(ocr, dict):
            ocr = {}
        searched = normalize_party_name(str(ocr.get("searched_name") or ""))
        if searched and not is_book_page_label(searched):
            groups.setdefault(searched, []).append(doc)
            if searched not in order:
                order.append(searched)
            continue
        primary.append(doc)

    grouped: list[dict[str, Any]] = []
    for name in order:
        docs = groups.get(name) or []
        if not docs:
            continue
        grouped.append(
            {
                "name": name,
                "documents": docs,
                "document_count": len(docs),
            }
        )
    return grouped, primary


def resolve_name_searches_for_report(
    plan_json: dict[str, Any] | None,
    *,
    documents: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    """Return only the party names that were searched by the Name Searcher node."""
    if not isinstance(plan_json, dict):
        return []

    node_results = plan_json.get("node_results") or {}
    searcher_result = node_results.get("name_searcher")
    if not isinstance(searcher_result, dict):
        for value in node_results.values():
            if isinstance(value, dict) and "names_searched" in value:
                searcher_result = value
                break

    if not isinstance(searcher_result, dict):
        return []

    stored_entries = searcher_result.get("name_search_entries")
    if isinstance(stored_entries, list):
        entries = [
            {
                "name": normalize_party_name(str(entry.get("name") or "")),
                "source": str(entry.get("source") or "Recorder").strip() or "Recorder",
            }
            for entry in stored_entries
            if isinstance(entry, dict) and str(entry.get("name") or "").strip()
        ]
        if entries:
            return entries

    searched_names = searcher_result.get("names_searched") or []
    if not isinstance(searched_names, list):
        return []

    if documents:
        return build_name_searcher_report_entries(documents, searched_names)

    entries = []
    seen: set[str] = set()
    for raw_name in searched_names:
        name = normalize_party_name(str(raw_name))
        if not name or name in seen:
            continue
        seen.add(name)
        entries.append({"name": name, "source": "Recorder"})
    return entries
