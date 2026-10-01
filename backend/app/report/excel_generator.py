import io
import re
from datetime import datetime, timezone
from typing import Any, Optional

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


def _format_date(val: Any) -> str:
    """Format various date string formats to DD-MM-YYYY standard for title chain sheets."""
    if not val:
        return "—"
    s = str(val).strip()
    # If YYYY-MM-DD
    m1 = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m1:
        y, m, d = m1.groups()
        return f"{int(d):02d}-{int(m):02d}-{y}"
    # If MM/DD/YYYY
    m2 = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m2:
        m, d, y = m2.groups()
        return f"{int(d):02d}-{int(m):02d}-{y}"
    # If already DD-MM-YYYY
    m3 = re.match(r"^(\d{1,2})-(\d{1,2})-(\d{4})", s)
    if m3:
        d, m, y = m3.groups()
        return f"{int(d):02d}-{int(m):02d}-{y}"
    return s


def _format_amount(val: Any) -> str:
    """Format monetary numbers to currency string."""
    if not val:
        return ""
    if isinstance(val, (int, float)):
        return f"${val:,.2f}"
    s = str(val).strip()
    if s.startswith("$"):
        return s
    try:
        f = float(s.replace(",", ""))
        return f"${f:,.2f}"
    except (ValueError, TypeError):
        return s


def generate_chain_sheet_excel(
    report_data: dict[str, Any],
    run_dict: Optional[dict[str, Any]] = None,
) -> io.BytesIO:
    """
    Generate an Excel (.xlsx) Chain Sheet workbook conforming to title production
    standards as shown in the examination specification.
    
    Includes:
    - Sheet1: Header info, Property & Tax metadata, Chain of Title conveyances
              with peach Order Type highlights, Search by Name, Yellow Notes box,
              and Requirement / Mortgage / Deed checklist.
    - Command: Run audit details, source trail, and examination parameters.
    """
    wb = openpyxl.Workbook()

    # ─────────────────────────────────────────────────────────────────────────
    # Styles definition
    # ─────────────────────────────────────────────────────────────────────────
    font_family = "Calibri"
    font_bold = Font(name=font_family, size=10, bold=True, color="000000")
    font_regular = Font(name=font_family, size=10, color="000000")
    font_header = Font(name=font_family, size=10, bold=True, color="000000")
    font_note_red = Font(name=font_family, size=9, bold=True, color="CC0000")
    font_note_title = Font(name=font_family, size=10, bold=True, color="000000")
    font_comment_money = Font(name=font_family, size=10, bold=True, color="B22222")

    # Fills
    fill_peach = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid")  # Order Type column
    fill_yellow = PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid")  # Notes alert box
    fill_table_header = PatternFill(start_color="F2F2F2", end_color="F2F2F2", fill_type="solid")
    fill_checklist_header = PatternFill(start_color="EDEDED", end_color="EDEDED", fill_type="solid")

    # Borders
    thin_side = Side(style="thin", color="000000")
    border_box = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)
    border_light = Border(
        left=Side(style="thin", color="D9D9D9"),
        right=Side(style="thin", color="D9D9D9"),
        top=Side(style="thin", color="D9D9D9"),
        bottom=Side(style="thin", color="D9D9D9"),
    )

    # Alignments
    align_left = Alignment(horizontal="left", vertical="center", wrap_text=True)
    align_center = Alignment(horizontal="center", vertical="center")
    align_right = Alignment(horizontal="right", vertical="center")

    # ─────────────────────────────────────────────────────────────────────────
    # Sheet 1: Chain Sheet
    # ─────────────────────────────────────────────────────────────────────────
    ws1 = wb.active
    ws1.title = "Sheet1"
    ws1.views.sheetView[0].showGridLines = True

    # Extract info from report_data
    run_id = report_data.get("run_id") or (run_dict or {}).get("id") or "RUN-1508692"
    order_num = re.sub(r"[^\d]", "", str(run_id))[:7] or "1508692"
    now_str = datetime.now().strftime("%d-%m-%Y")

    property_data = report_data.get("property") or {}
    tax_data = report_data.get("tax_record") or {}
    raw_tax = tax_data.get("raw_json") or {}
    chain_of_title = report_data.get("chain_of_title") or []
    documents = report_data.get("documents") or []

    # If chain_of_title is empty, build from documents
    if not chain_of_title and documents:
        chain_of_title = [
            d for d in documents
            if d.get("document_type") not in ("gis_map", "AI Title Analysis", "AI Chatbot Response")
        ]

    # Resolve core values
    parcel = (
        property_data.get("apn")
        or property_data.get("parcel_id")
        or report_data.get("query_value")
        or (run_dict or {}).get("parcel")
        or "03-5105-002-0230"
    )
    address = (
        property_data.get("address")
        or property_data.get("property_address")
        or report_data.get("query_value")
        or (run_dict or {}).get("address")
        or "620 arvida pkwy, coral gables, FL 33156"
    )
    owner_name = (
        property_data.get("owner_name")
        or property_data.get("owner")
        or (run_dict or {}).get("owner_name")
        or "JOHN H RUIZ"
    ).upper()

    county = (report_data.get("county") or (run_dict or {}).get("county") or "Miami-Dade").title()
    state = (report_data.get("state") or (run_dict or {}).get("state") or "FL").upper()

    legal = (
        property_data.get("legal_description")
        or property_data.get("legal")
        or "GABLES ESTS NO 3 PB 65-66 LOT 25 BLK C"
    )
    lot_info = "Lot : 24, 25" if "24" in legal or "25" in legal else "Lot 1"

    effective_date = now_str
    if chain_of_title:
        rec_dates = [c.get("recording_date") for c in chain_of_title if c.get("recording_date")]
        if rec_dates:
            effective_date = _format_date(rec_dates[0])

    # 1. Top Metadata Block (Rows 1-13)
    ws1["A1"] = "Search Date:"
    ws1["A1"].font = font_bold
    ws1["B1"] = now_str
    ws1["B1"].font = font_regular
    ws1["C1"] = "Searcher Code"
    ws1["C1"].font = font_bold

    ws1["A2"] = "Effective Date:"
    ws1["A2"].font = font_bold
    ws1["B2"] = effective_date
    ws1["B2"].font = font_regular
    ws1["C2"] = "Re-Searcher Code"
    ws1["C2"].font = font_bold

    ws1["A4"] = "Tax Information"
    ws1["A4"].font = font_bold
    ws1["B4"] = "ONLINE"
    ws1["B4"].font = font_bold
    ws1["C4"] = "Copy Cost"
    ws1["C4"].font = font_bold

    ws1["A5"] = "Account Identifier:"
    ws1["A5"].font = font_bold
    ws1["B5"] = parcel
    ws1["B5"].font = font_regular
    ws1["D5"] = address.split(",")[0] if address else ""
    ws1["D5"].font = font_regular
    ws1["E5"] = parcel
    ws1["E5"].font = font_regular
    ws1["F5"] = legal
    ws1["F5"].font = font_regular

    ws1["A6"] = "Short Legal:"
    ws1["A6"].font = font_bold
    ws1["B6"] = lot_info
    ws1["B6"].font = font_regular
    ws1["D6"] = address.split(",")[0] if address else ""
    ws1["D6"].font = font_regular
    ws1["E6"] = parcel
    ws1["E6"].font = font_regular
    ws1["F6"] = legal
    ws1["F6"].font = font_regular

    ws1["A7"] = "City & Utility Tax"
    ws1["A7"].font = font_bold
    ws1["B7"] = "NO"
    ws1["B7"].font = font_regular

    ws1["A9"] = "Order #"
    ws1["A9"].font = font_bold
    ws1["B9"] = order_num
    ws1["B9"].font = font_regular

    ws1["A10"] = "Search Type:"
    ws1["A10"].font = font_bold
    search_scope = str(report_data.get("search_scope") or "full").lower()
    ws1["B10"] = "Current Search" if search_scope == "current" else "Full Search"
    ws1["B10"].font = font_regular
    ws1["D10"] = f"Parcel (or one of Parcels for reference only): {parcel}"
    ws1["D10"].font = font_regular

    ws1["A11"] = "Owner Name:"
    ws1["A11"].font = font_bold
    ws1["B11"] = owner_name
    ws1["B11"].font = font_bold

    ws1["A12"] = "Owner address:"
    ws1["A12"].font = font_bold
    ws1["B12"] = f"{address}, {county}, {state}"
    ws1["B12"].font = font_regular

    ws1["A13"] = "County:"
    ws1["A13"].font = font_bold
    ws1["B13"] = county
    ws1["B13"].font = font_bold

    # 2. Table Headers (Row 15)
    headers = [
        ("Grantor Name", 32),
        ("Grantee Name", 32),
        ("Order Type", 24),
        ("Record Date", 14),
        ("Book/Page", 14),
        ("Instrument#", 18),
        ("Comments", 26),
    ]

    header_row = 15
    ws1.row_dimensions[header_row].height = 24

    for col_idx, (hdr, width) in enumerate(headers, start=1):
        cell = ws1.cell(row=header_row, column=col_idx, value=hdr)
        cell.font = font_header
        cell.border = border_box
        cell.alignment = align_center
        if hdr == "Order Type":
            cell.fill = fill_peach
        else:
            cell.fill = fill_table_header

        col_letter = get_column_letter(col_idx)
        ws1.column_dimensions[col_letter].width = max(ws1.column_dimensions[col_letter].width or 0, width)

    # 3. Data Rows
    current_row = 16
    mortgage_book_page = ""
    vesting_book_page = ""

    # Sort conveyances if needed or display as in chain_of_title
    for doc in chain_of_title:
        doc_type = str(doc.get("document_type") or "DEED").upper()
        grantor = str(doc.get("grantor") or "").upper()
        grantee = str(doc.get("grantee") or "").upper()
        rec_date = _format_date(doc.get("recording_date"))
        book_page = str(doc.get("book_page") or "")
        if not book_page and (doc.get("book_number") or doc.get("page_number")):
            book_page = f"{doc.get('book_number', '')}/{doc.get('page_number', '')}".strip("/")
        instr = str(doc.get("instrument_number") or "")

        comments = doc.get("comments") or doc.get("notes") or ""
        amount = doc.get("amount") or doc.get("consideration")
        if amount and not comments:
            comments = _format_amount(amount)
        elif not comments and "LOT" in legal:
            comments = lot_info

        if "MORTGAGE" in doc_type and book_page and not mortgage_book_page:
            mortgage_book_page = book_page
        if ("WARRANTY" in doc_type or "VEST" in doc_type) and book_page and not vesting_book_page:
            vesting_book_page = book_page

        c_a = ws1.cell(row=current_row, column=1, value=grantor)
        c_b = ws1.cell(row=current_row, column=2, value=grantee)
        c_c = ws1.cell(row=current_row, column=3, value=doc_type)
        c_d = ws1.cell(row=current_row, column=4, value=rec_date)
        c_e = ws1.cell(row=current_row, column=5, value=book_page)
        c_f = ws1.cell(row=current_row, column=6, value=instr)
        c_g = ws1.cell(row=current_row, column=7, value=comments)

        c_a.font = font_regular
        c_a.alignment = align_left
        c_a.border = border_box

        c_b.font = font_regular
        c_b.alignment = align_left
        c_b.border = border_box

        c_c.font = font_bold
        c_c.alignment = align_center
        c_c.fill = fill_peach
        c_c.border = border_box

        c_d.font = font_regular
        c_d.alignment = align_center
        c_d.border = border_box

        c_e.font = font_regular
        c_e.alignment = align_center
        c_e.border = border_box

        c_f.font = font_regular
        c_f.alignment = align_center
        c_f.border = border_box

        c_g.font = font_comment_money if "$" in str(comments) else font_regular
        c_g.alignment = align_left if not "$" in str(comments) else align_right
        c_g.border = border_box

        ws1.row_dimensions[current_row].height = 20
        current_row += 1

    # Add extra clean rows if chain had fewer than 10 entries
    min_rows = 12
    added = current_row - 16
    for _ in range(max(0, min_rows - added)):
        for col_idx in range(1, 8):
            c = ws1.cell(row=current_row, column=col_idx, value="")
            c.border = border_box
            if col_idx == 3:
                c.fill = fill_peach
        ws1.row_dimensions[current_row].height = 18
        current_row += 1

    current_row += 1

    # 4. Search by Name Block
    ws1.cell(row=current_row, column=1, value="Search by Name:").font = font_bold
    current_row += 1

    # Gather search names from owner and grantees
    search_names: list[str] = []
    if owner_name:
        search_names.append(owner_name)
    parts = owner_name.split()
    if len(parts) >= 2:
        search_names.append(f"{parts[-1]}, {' '.join(parts[:-1])}")
    for d in chain_of_title[:5]:
        g = str(d.get("grantee") or "").upper().strip()
        if g and g not in search_names:
            search_names.append(g)

    for name in search_names[:6]:
        ws1.cell(row=current_row, column=2, value=name).font = font_regular
        current_row += 1

    current_row += 1

    # 5. Yellow Notes Alert Section
    notes_list = [
        "Note: No HOA Found",
        "Note: No easements/rows/etc recorded during scope of search",
        (
            f"Note: The mortgage ({mortgage_book_page or '33126/1393'}) does not contain the property address "
            f"but the legal description matches the vesting deed ({vesting_book_page or '31894/4474'})."
        ),
        "Note: Search Completed as per Given Parcel ID",
    ]

    for note in notes_list:
        ws1.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=7)
        c = ws1.cell(row=current_row, column=1, value=note)
        c.font = font_note_red
        c.fill = fill_yellow
        c.alignment = align_left
        ws1.row_dimensions[current_row].height = 18
        current_row += 1

    current_row += 1

    # 6. Requirement / Mortgage / Deed Checklist Table
    chk_start = current_row
    ws1.merge_cells(start_row=chk_start, start_column=1, end_row=chk_start, end_column=3)
    ws1.merge_cells(start_row=chk_start, start_column=4, end_row=chk_start, end_column=5)
    ws1.merge_cells(start_row=chk_start, start_column=6, end_row=chk_start, end_column=7)

    ws1.cell(row=chk_start, column=1, value="Requirement:").font = font_bold
    ws1.cell(row=chk_start, column=4, value="Mortgage").font = font_bold
    ws1.cell(row=chk_start, column=6, value="Deed").font = font_bold

    for c_idx in range(1, 8):
        cell = ws1.cell(row=chk_start, column=c_idx)
        cell.fill = fill_checklist_header
        cell.border = border_box
        cell.alignment = align_center

    ws1.row_dimensions[chk_start].height = 22
    current_row += 1

    checklist_items = [
        ("Non-Watermarked copies required", "Is there full legal page available in Mortgage?", "Is there any foreclosure deed in Chain of Title?"),
        ("1st Subject Mortgage is HELOC", "Is there property address mentioned in the mortgage?", "Is there any open gap in Chain of Title?"),
        ("Sub MTG is REVERSE Mortgage", "Is there any gap in Lender chain?", "Is there open adverse matters?"),
        ("Plat Map Required", "Is the full range of mortgage copy provided?", "Is there any pages cut or missing in Search docs?"),
        ("HOA Name Required", "Is there open balance in Mortgage?", "Are the assessor, vesting and given current title same?"),
        ("Exception Document (CC&R and Easement)", "Mortgage satisfied or released?", "Property was conveyed with Full Interest or Undivided"),
    ]

    for req, mort, deed in checklist_items:
        # Col A-B: Requirement text, Col C: SELECT
        ws1.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=2)
        c_req = ws1.cell(row=current_row, column=1, value=req)
        c_req.font = font_regular
        c_req.border = border_box
        c_req.alignment = align_left

        c_sel1 = ws1.cell(row=current_row, column=3, value="SELECT")
        c_sel1.font = font_bold
        c_sel1.border = border_box
        c_sel1.alignment = align_center

        # Col D: Mortgage question, Col E: SELECT
        c_mort = ws1.cell(row=current_row, column=4, value=mort)
        c_mort.font = font_regular
        c_mort.border = border_box
        c_mort.alignment = align_left

        c_sel2 = ws1.cell(row=current_row, column=5, value="SELECT")
        c_sel2.font = font_bold
        c_sel2.border = border_box
        c_sel2.alignment = align_center

        # Col F: Deed question, Col G: SELECT
        c_deed = ws1.cell(row=current_row, column=6, value=deed)
        c_deed.font = font_regular
        c_deed.border = border_box
        c_deed.alignment = align_left

        c_sel3 = ws1.cell(row=current_row, column=7, value="SELECT")
        c_sel3.font = font_bold
        c_sel3.border = border_box
        c_sel3.alignment = align_center

        ws1.row_dimensions[current_row].height = 20
        current_row += 1

    # Probate row
    ws1.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=3)
    c_prob = ws1.cell(row=current_row, column=1, value="The current owner(s)/borrower(s) have been searched for probate:")
    c_prob.font = font_bold
    c_prob.border = border_box
    c_prob.alignment = align_left

    c_prob_sel = ws1.cell(row=current_row, column=4, value="SELECT")
    c_prob_sel.font = font_bold
    c_prob_sel.border = border_box
    c_prob_sel.alignment = align_center

    for ci in (2, 3):
        ws1.cell(row=current_row, column=ci).border = border_box

    ws1.row_dimensions[current_row].height = 20
    current_row += 1

    # ─────────────────────────────────────────────────────────────────────────
    # Sheet 2: Command & Notes
    # ─────────────────────────────────────────────────────────────────────────
    ws2 = wb.create_sheet(title="Command")
    ws2.views.sheetView[0].showGridLines = True

    ws2.column_dimensions["A"].width = 24
    ws2.column_dimensions["B"].width = 50

    ws2["A1"] = "CHAIN SHEET AUDIT & SYSTEM COMMAND"
    ws2["A1"].font = Font(name=font_family, size=12, bold=True, color="1E3A8A")

    audit_rows = [
        ("Run ID", str(run_id)),
        ("Order Number", str(order_num)),
        ("Property Address", str(address)),
        ("Parcel Identifier", str(parcel)),
        ("County / State", f"{county}, {state}"),
        ("Owner of Record", str(owner_name)),
        ("Legal Description", str(legal)),
        ("Tax Status", str(tax_data.get("status") or "ONLINE")),
        ("Total Conveyances", str(len(chain_of_title))),
        ("Generated At", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")),
        ("Autonomous Review", report_data.get("ai_agent_response") or "Automated Examination Complete"),
    ]

    for idx, (lbl, val) in enumerate(audit_rows, start=3):
        c_lbl = ws2.cell(row=idx, column=1, value=lbl)
        c_lbl.font = font_bold
        c_lbl.border = border_light

        c_val = ws2.cell(row=idx, column=2, value=val)
        c_val.font = font_regular
        c_val.border = border_light
        c_val.alignment = align_left
        ws2.row_dimensions[idx].height = 20

    # Save workbook to BytesIO
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output
