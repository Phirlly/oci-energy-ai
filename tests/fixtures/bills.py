"""Independently invented public data; never derived from a customer bill."""

FACTS = dict(supplier="Juniper Power", account="DEMO-A71", meter="MTR-EXAMPLE",
             service="electricity", usage_kind="consumption", unit="kWh",
             period_start="2024-02-01", period_end="2024-03-01", days=29,
             currency="USD", consumption="580", current_total="91.50",
             charges=[dict(label="Energy including service fee", amount="90", role="additive"),
                      dict(label="Included service fee", amount="12", role="included"),
                      dict(label="Tax", amount="3", role="additive"),
                      dict(label="Energy credit", amount="-1.50", role="additive"),
                      dict(label="Previous balance", amount="40", role="excluded")])
TEXT = """Juniper Power / Electricity
Account DEMO-A71 / Meter MTR-EXAMPLE
Service 2024-02-01 to 2024-03-01 / 29 days
Consumption 580 kWh / Currency USD
Current electricity charges 91.50
Energy including service fee 90.00
Included service fee 12.00
Tax 3.00
Energy credit -1.50
Previous balance 40.00
Amount due 131.50"""

def candidate():
    from copy import deepcopy
    evidence = {name: {"page": 1, "quote": TEXT} for name in FACTS if name != "charges"}
    evidence.update({f"charges.{i}": {"page": 1, "quote": TEXT}
                     for i in range(len(FACTS["charges"]))})
    return {"facts": deepcopy(FACTS), "evidence": evidence}

def pdf_bytes(text=TEXT, *, pages=1, encrypted=False):
    from io import BytesIO
    from pypdf import PdfWriter
    from pypdf.generic import (NameObject, DictionaryObject, DecodedStreamObject)
    writer = PdfWriter()
    for _ in range(pages):
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                 NameObject("/Subtype"): NameObject("/Type1"),
                                 NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
        stream = DecodedStreamObject()
        escaped = [line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
                   for line in text.splitlines()]
        stream.set_data(("BT /F1 10 Tf 40 750 Td 14 TL " +
                         " T* ".join(f"({line}) Tj" for line in escaped) + " ET").encode("ascii"))
        page[NameObject("/Contents")] = stream
    if encrypted:
        writer.encrypt("test-password")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()
