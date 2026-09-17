import pytest
from app.extraction.florida_tax_extractors import tax_record_from_florida_data

def test_tax_record_from_county_taxes_data():
    scraped = {
        "url": "https://county-taxes.net/fl-miamidade/property-tax/test-account",
        "account_number": "Real Estate Account #30-4009-096-0060",
        "owner": "MARIA C MARRERO LE",
        "situs": "2125 SW 93 CT, FL 33165",
        "exemptions_summary": "Homestead Exemption",
        "amount_due": 0.0,
        "amount_due_message": "Your account is paid in full.",
        "last_payment": "11/06/2025 for $2,755.82",
        "account_history": [
            {
                "bill": "2025 Annual Bill",
                "amount_due": "$0.00",
                "status": "Paid $2,755.82",
                "date": "11/06/2025",
                "action": "Receipt #PTBTE-26-036275"
            },
            {
                "bill": "2024 Annual Bill",
                "amount_due": "$0.00",
                "status": "Paid $2,678.01",
                "date": "11/21/2024",
                "action": "Receipt #PTBTE-25-101924"
            }
        ],
        "last_two_bills": [
            {
                "bill_title": "2025 Annual Bill",
                "bill_summary": {
                    "bill": "2025 Annual Bill",
                    "millage_code": "3000",
                    "amount_due": "$0.00",
                    "status": "PAID"
                },
                "ad_valorem_taxes": {
                    "headers": ["TAXING AUTHORITY", "MILLAGE", "TAX"],
                    "rows": [["Miami-Dade County", "4.574", "$429.00"]]
                },
                "non_ad_valorem_assessments": {
                    "headers": ["LEVYING AUTHORITY", "AMOUNT"],
                    "rows": [["GARBAGE", "$702.00"]]
                },
                "combined_taxes": "$2,870.65",
                "exemptions": {"HOMESTEAD": "$25,000"}
            },
            {
                "bill_title": "2024 Annual Bill",
                "bill_summary": {
                    "bill": "2024 Annual Bill",
                    "millage_code": "3000",
                    "amount_due": "$0.00",
                    "status": "PAID"
                },
                "combined_taxes": "$2,789.59"
            }
        ]
    }

    record = tax_record_from_florida_data(scraped, apn="30-4009-096-0060")
    assert record.tax_account == "Real Estate Account #30-4009-096-0060"
    assert record.tax_year == "2025"
    assert record.owner_name == "MARIA C MARRERO LE"
    assert record.property_address == "2125 SW 93 CT, FL 33165"
    assert record.amount_due == 0.0
    assert record.raw_json["platform"] == "county-taxes"
    assert len(record.raw_json["last_two_bills"]) == 2
    assert record.raw_json["last_two_bills"][0]["bill_summary"]["millage_code"] == "3000"
    assert len(record.raw_json["account_history"]) == 2
