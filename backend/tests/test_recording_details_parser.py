from app.extraction.recording_details_parser import parse_recording_details


SAMPLE_DEED_TEXT = """
CORPORATE WARRANTY DEED
CFN: 20190711430
Book: 31687 Page: 1679
11/13/2019 12:39:13 PM
Deed Doc Fee: 2,205.00

Prepared By: Gayon Gilbert, DHI Title of Florida, Inc.
Order No.: 100-191600470
Parcel I.D. (folio) Number: 30-6924-001-0030
Sales Price: $367,490.00
Documentary Stamps: $ 2,205.00

This deed made this 30th day of October, 2019
Grantor: D.R. Horton, Inc., a Delaware Corporation
Grantee: Juan A. Morales, A Single Man

Legal Description: Lot 3, Block 1, SUMMERVILLE VILLAS, recorded in Plat Book 165,
Pages 41-1 and 41-2, of the Public Records of Miami-Dade County, Florida.
"""


def test_parse_miami_dade_warranty_deed_fields():
    details = parse_recording_details(SAMPLE_DEED_TEXT, document_hint="Corporate Warranty Deed")

    assert details["document_type"] == "Corporate Warranty Deed"
    assert details["book"] == "31687"
    assert details["page"] == "1679"
    assert details["book_page"] == "31687/1679"
    assert details["instrument_number"] == "20190711430"
    assert "367,490.00" in details["sale_price"]
    assert "2,205.00" in details["documentary_stamps"]
    assert details["parcel_id"] == "30-6924-001-0030"
    assert details["order_number"] == "100-191600470"
    assert "D.R. Horton" in details["grantor"]
    assert "Morales" in details["grantee"]
    assert "SUMMERVILLE VILLAS" in details["legal_description"]


def test_parse_recording_details_empty_text():
    assert parse_recording_details("") == {}


WARRANTY_DEED_TEXT = """
WARRANTY DEED
This deed made this 29th day of December, 2021
between LIFT STATIONS OF SOUTH FLORIDA, LLC, a Florida Limited Liability Company,
and MIAMI EDGE INVESTMENTS, INC., a Florida corporation,
in consideration of the sum of TEN AND NO/100 DOLLARS ($10.00) and other good and valuable considerations,
the receipt and sufficiency of which are hereby acknowledged,
grants, bargains, sells, alienates, remises, releases, conveys and confirms unto the Grantee
the following described property in Miami-Dade County, Florida:
Lot 3, Block 30, FLORAL PARK, according to the Plat thereof, as recorded in Plat Book 8, Page 3,
of the Public Records of Miami-Dade County, Florida.
Parcel Identification No.: 30-3122-052-5300
"""


def test_parse_warranty_deed_consideration_and_parties():
    details = parse_recording_details(WARRANTY_DEED_TEXT, document_hint="Warranty Deed")

    assert "10.00" in str(details.get("consideration"))
    assert details.get("parcel_id") == "30-3122-052-5300"
    assert "FLORAL PARK" in str(details.get("legal_description"))
    assert details.get("warranty") == "Warranty Deed"
