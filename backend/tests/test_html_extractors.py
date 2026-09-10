from app.extraction.html_extractors import extract_documents_from_html, extract_parcel_from_html


def test_extract_parcel_from_table():
    html = """
    <table>
      <tr><th>Owner</th><td>John Smith</td></tr>
      <tr><th>APN</th><td>123-45-678</td></tr>
      <tr><th>Property Address</th><td>123 Main St</td></tr>
      <tr><th>Assessed Value</th><td>$45,000</td></tr>
    </table>
    """
    parcel = extract_parcel_from_html(html)
    assert parcel.owner_name == "John Smith"
    assert parcel.apn == "123-45-678"
    assert parcel.property_address == "123 Main St"
    assert parcel.assessed_value == 45000.0


def test_extract_documents_from_table():
    html = """
    <table>
      <tr><th>Type</th><th>Book/Page</th><th>Grantor</th><th>Grantee</th></tr>
      <tr><td>Warranty Deed</td><td>1234/56</td><td>Smith</td><td>Jones</td></tr>
    </table>
    """
    docs = extract_documents_from_html(html)
    assert len(docs) == 1
    assert docs[0].document_type == "Warranty Deed"
    assert docs[0].grantor == "Smith"
