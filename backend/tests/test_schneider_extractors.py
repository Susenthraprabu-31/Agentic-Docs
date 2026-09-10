from app.extraction.schneider_extractors import (
    extract_schneider_qpublic_from_html,
    parcel_record_from_schneider_data,
)


HONOLULU_DETAIL_HTML = """
<html><body>
<div id="ctlBodyPane">
  <span class="widgetLabel">Parcel Number</span>
  <span class="widgetValue">390300650013</span>
  <span id="ctlBodyPane_ctl00_ctl01_lblLocationAddress">486 KAWAIHAE ST APT F</span>
  <span class="widgetLabel">Location Address</span>
  <span class="widgetValue">486 KAWAIHAE ST APT F</span>
  <span class="widgetLabel">Project Name</span>
  <span class="widgetValue">KAWAIHAE CRESCENT E</span>
  <span id="ctlBodyPane_ctl00_ctl01_lblLegalInformation">APT 486F KAWAIHAE CRESCENT EAST CONDO MAP 246</span>
  <span class="widgetLabel">Legal Information</span>
  <span class="widgetValue">APT 486F KAWAIHAE CRESCENT EAST CONDO MAP 246</span>
  <span class="widgetLabel">Property Class</span>
  <span class="widgetValue">RESIDENTIAL</span>
  <span class="widgetLabel">Land Area (Acres)</span>
  <span class="widgetValue">0.0000</span>
  <h2>Owner Information</h2>
  <table>
    <tr><th>Owner Name</th><th>Owner Type</th></tr>
    <tr><td>ALVARADO, FRED A</td><td>Fee Owner</td></tr>
    <tr><td>ALVARADO, LIANE B</td><td>Fee Owner</td></tr>
  </table>
  <h2>Assessment Information</h2>
  <table>
    <tr>
      <th>Tax Year</th><th>Property Class</th><th>Assessed Land Value</th>
      <th>Assessed Building Value</th><th>Total Property Assessed Value</th>
      <th>Total Net Taxable Value</th>
    </tr>
    <tr>
      <td>2024</td><td>RESIDENTIAL</td><td>$536,000</td>
      <td>$268,200</td><td>$804,200</td><td>$684,200</td>
    </tr>
  </table>
  <h2>Sales Information</h2>
  <table>
    <tr>
      <th>Sale Date</th><th>Sale Price</th><th>Grantor</th><th>Grantee</th><th>Document Type</th>
    </tr>
    <tr>
      <td>03/15/2019</td><td>$625,000</td><td>SMITH, JANE</td><td>ALVARADO, FRED A</td><td>Warranty Deed</td>
    </tr>
  </table>
</div>
</body></html>
"""

HONOLULU_PANE_TEXT_HTML = """
<html><body>
<div id="ctlBodyPane">
Parcel Information
Parcel Number
390300650012
Location Address
486 KAWAIHAE ST UNIT G
Project Name
KAWAIHAE CRESCENT E
Legal Information
APT 486-G "KAWAIHAE CRESCENT EAST" CONDO MAP 246 TOG/2 PKG STALLS
Property Class
RESIDENTIAL
Land Area (Acres)
0.0000
</div>
</body></html>
"""


def test_extract_honolulu_schneider_detail():
    parcel = extract_schneider_qpublic_from_html(
        HONOLULU_DETAIL_HTML,
        page_url="https://qpublic.schneidercorp.com/Application.aspx?KeyValue=390300650013",
    )
    assert parcel.apn == "390300650013"
    assert parcel.owner_name == "ALVARADO, FRED A; ALVARADO, LIANE B"
    assert "Owner Type" not in (parcel.owner_name or "")
    assert parcel.property_address == "486 KAWAIHAE ST APT F"
    assert parcel.assessed_value == 804200.0
    assert parcel.legal_desc == "APT 486F KAWAIHAE CRESCENT EAST CONDO MAP 246"
    assert parcel.raw_json.get("property class") == "RESIDENTIAL" or parcel.raw_json["assessment_rows"][0]["Property Class"] == "RESIDENTIAL"
    assert parcel.raw_json.get("assessment_rows")
    assert parcel.raw_json.get("owner_rows")
    assert parcel.raw_json.get("chain_of_title")
    assert parcel.raw_json["chain_of_title"][0]["grantor"] == "SMITH, JANE"
    assert parcel.raw_json.get("source_url")


def test_extract_address_and_legal_from_pane_text_layout():
    parcel = extract_schneider_qpublic_from_html(HONOLULU_PANE_TEXT_HTML)
    assert parcel.apn == "390300650012"
    assert parcel.property_address == "486 KAWAIHAE ST UNIT G"
    assert "KAWAIHAE CRESCENT EAST" in (parcel.legal_desc or "")
    assert parcel.raw_json.get("location address") == "486 KAWAIHAE ST UNIT G"
    assert parcel.raw_json.get("legal information")


def test_owner_table_header_not_used_as_owner_name():
    data = {
        "Owner Name": "Owner Type",
        "owner_rows": [{"Owner Name": "ALVARADO, FRED A", "Owner Type": "Fee Owner"}],
    }
    parcel = parcel_record_from_schneider_data(data)
    assert parcel.owner_name == "ALVARADO, FRED A"


def test_sales_information_instrument_only_rows():
    html = """
    <div id="ctlBodyPane">
      <h2>Sales Information</h2>
      <table>
        <tr>
          <th>Sale Date</th><th>Sale Price</th><th>Instrument Number</th><th>Document Type</th>
        </tr>
        <tr>
          <td>03/19/2008</td><td>$500,000</td><td>2008-044514</td><td>Warranty Deed</td>
        </tr>
      </table>
    </div>
    """
    parcel = extract_schneider_qpublic_from_html(html)
    chain = parcel.raw_json.get("chain_of_title") or []
    assert len(chain) == 1
    assert chain[0]["instrument_number"] == "2008-044514"
    assert chain[0]["recording_date"] == "03/19/2008"
    assert chain[0]["sale_price"] == "$500,000"
    assert chain[0]["document_type"] == "Warranty Deed"


def test_parcel_record_from_schneider_data_merges_assessment():
    data = {
        "Parcel Number": "123",
        "Owner Names": "SMITH, JOHN",
        "assessment_rows": [{"Total Property Assessed Value": "$100,000"}],
    }
    parcel = parcel_record_from_schneider_data(data)
    assert parcel.apn == "123"
    assert parcel.assessed_value == 100000.0
