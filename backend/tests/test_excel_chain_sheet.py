import io
import uuid
import openpyxl
import pytest
from app.report.excel_generator import generate_chain_sheet_excel
from app.report.report_builder import ReportBuilder


def test_generate_chain_sheet_excel_structure_and_styling():
    report_data = {
        "run_id": "run-test-1508692",
        "state": "FL",
        "county": "miami-dade",
        "query_type": "address",
        "query_value": "620 arvida pkwy",
        "property": {
            "apn": "03-5105-002-0230",
            "address": "620 arvida pkwy, coral gables, FL 33156",
            "owner_name": "JOHN H RUIZ",
            "legal_description": "GABLES ESTS NO 3 PB 65-66 LOT 25 BLK C",
        },
        "tax_record": {
            "status": "Paid",
            "gross_tax": 18450.25,
            "tax_account": "03-5105-002-0230",
        },
        "chain_of_title": [
            {
                "grantor": "AP 620 LLC",
                "grantee": "BENJAMIN LEON JR AND SILVIA LEON",
                "document_type": "WARRANTY DEED",
                "recording_date": "2010-12-21",
                "book_page": "27529/1785",
                "instrument_number": "2010 R 853064",
                "comments": "Lot 25",
            },
            {
                "grantor": "BENJAMIN LEON JR AND SILVIA LEON",
                "grantee": "JOHN H RUIZ",
                "document_type": "WARRANTY DEED",
                "recording_date": "2020-04-13",
                "book_page": "31894/4474",
                "instrument_number": "2020 R 223930",
                "comments": "Lot : 24,25",
            },
            {
                "grantor": "JOHN H RUIZ",
                "grantee": "CITY NATIONAL BANK OF FLORIDA",
                "document_type": "MORTGAGE",
                "recording_date": "2022-04-12",
                "book_page": "33126/1399",
                "instrument_number": "2022 R 301183",
                "amount": 20000000.0,
                "comments": "$20,000,000.00",
            },
        ],
    }

    excel_io = generate_chain_sheet_excel(report_data)
    assert isinstance(excel_io, io.BytesIO)
    assert excel_io.getbuffer().nbytes > 0

    # Load workbook back to inspect structure
    wb = openpyxl.load_workbook(excel_io)
    assert "Sheet1" in wb.sheetnames
    assert "Command" in wb.sheetnames

    ws1 = wb["Sheet1"]

    # Check top metadata
    assert ws1["A1"].value == "Search Date:"
    assert ws1["A4"].value == "Tax Information"
    assert ws1["B4"].value == "ONLINE"
    assert ws1["A5"].value == "Account Identifier:"
    assert ws1["B5"].value == "03-5105-002-0230"
    assert ws1["A11"].value == "Owner Name:"
    assert "JOHN H RUIZ" in str(ws1["B11"].value)
    assert ws1["A13"].value == "County:"
    assert "Miami-Dade" in str(ws1["B13"].value)

    # Check table headers on Row 15
    assert ws1["A15"].value == "Grantor Name"
    assert ws1["B15"].value == "Grantee Name"
    assert ws1["C15"].value == "Order Type"
    assert ws1["D15"].value == "Record Date"
    assert ws1["E15"].value == "Book/Page"
    assert ws1["F15"].value == "Instrument#"
    assert ws1["G15"].value == "Comments"

    # Check peach fill on Order Type header
    header_fill = ws1["C15"].fill.start_color.rgb
    assert "FCE4D6" in str(header_fill).upper()

    # Check first conveyance row (Row 16)
    assert ws1["A16"].value == "AP 620 LLC"
    assert ws1["B16"].value == "BENJAMIN LEON JR AND SILVIA LEON"
    assert ws1["C16"].value == "WARRANTY DEED"
    assert ws1["D16"].value == "21-12-2010"
    assert ws1["E16"].value == "27529/1785"
    assert ws1["F16"].value == "2010 R 853064"
    assert ws1["G16"].value == "Lot 25"

    # Check Order Type cell fill on row 16
    row_fill = ws1["C16"].fill.start_color.rgb
    assert "FCE4D6" in str(row_fill).upper()

    # Check Mortgage row
    assert ws1["C18"].value == "MORTGAGE"
    assert "$20,000,000.00" in str(ws1["G18"].value)

    # Check Command sheet
    ws2 = wb["Command"]
    assert "CHAIN SHEET AUDIT" in str(ws2["A1"].value)
    assert ws2["B3"].value == "run-test-1508692"


@pytest.mark.asyncio
async def test_reports_excel_download_route():
    from fastapi.testclient import TestClient
    from app.api.main import app
    from app.db.supabase_client import get_memory_store

    run_id = f"test-excel-run-{uuid.uuid4().hex[:8]}"
    run_dict = {
        "id": run_id,
        "state": "FL",
        "county": "miami-dade",
        "query_type": "address",
        "query_value": "620 arvida pkwy",
        "parcel": "03-5105-002-0230",
        "address": "620 arvida pkwy",
        "owner_name": "JOHN H RUIZ",
        "status": "completed",
        "plan_json": {
            "node_results": {
                "assessor": {
                    "property": {
                        "apn": "03-5105-002-0230",
                        "address": "620 arvida pkwy",
                        "owner_name": "JOHN H RUIZ",
                        "legal_description": "GABLES ESTS NO 3 PB 65-66 LOT 25 BLK C",
                    }
                }
            }
        },
    }

    get_memory_store().runs[run_id] = run_dict

    client = TestClient(app)
    response = client.get(f"/reports/run/{run_id}/excel/download")

    assert response.status_code == 200
    assert "spreadsheetml" in response.headers.get("content-type", "")
    assert "attachment" in response.headers.get("content-disposition", "")
    assert ".xlsx" in response.headers.get("content-disposition", "")

    # Ensure returned stream is a valid workbook
    content = io.BytesIO(response.content)
    wb = openpyxl.load_workbook(content)
    assert "Sheet1" in wb.sheetnames
    assert "Command" in wb.sheetnames
