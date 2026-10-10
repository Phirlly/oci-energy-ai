"""One-page public illustrative invoice, computed from the same office source."""

from io import BytesIO

from pypdf import PdfWriter
from pypdf.generic import NameObject, DictionaryObject, DecodedStreamObject

from energy_ai.office.sample import office_profile


def office_bill_pdf():
    profile = office_profile()
    bill, tariff = profile['bill'], profile['tariff']
    lines = [
        (22, 'ENERGY AI / OFFICE DEMO'),
        (11, 'ILLUSTRATIVE ELECTRICITY STATEMENT'),
        (10, 'Public modeled data - not a utility-issued bill'),
        (10, ''),
        (12, 'Medium office / New York / ComStock building 2083'),
        (10, f"Service: {bill['period_start']} to {bill['period_end_exclusive']} (end exclusive)"),
        (10, '30 days / 2,880 intervals of 15 minutes'),
        (10, ''),
        (12, 'Usage and demand'),
        (10, f"Electricity consumption: {bill['energy_kwh']} kWh"),
        (10, f"Maximum 15-minute average demand: {bill['peak_kw']} kW"),
        (10, f"Peak interval ends: {profile['peak_interval_end']} (source clock)"),
        (10, ''),
        (12, 'Current electricity charges / USD'),
        (11, f"Energy at USD {tariff['energy_usd_per_kwh']}/kWh: {bill['energy_charge_usd']}"),
        (11, f"Demand at USD {tariff['demand_usd_per_kw']}/kW: {bill['demand_charge_usd']}"),
        (11, f"Fixed monthly charge: {bill['fixed_charge_usd']}"),
        (18, f"TOTAL CURRENT CHARGES: USD {bill['total_usd']}"),
        (10, ''),
        (11, 'Demo assumptions'),
        (10, 'Invented flat tariff. No tax, time-of-use rates or demand ratchets.'),
        (10, 'Public modeled profile, not measured customer data.'),
        (10, 'Unzoned source simulation clock; no civil timezone/DST conversion.'),
        (10, 'Charges rounded independently to cents and summed.'),
        (10, ''),
        (10, 'Source: DOE/NREL ComStock AMY2018 release 1 / CC BY 4.0'),
        (10, 'https://data.openei.org/submissions/4520'),
    ]
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                             NameObject('/Subtype'): NameObject('/Type1'),
                             NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):
        DictionaryObject({NameObject('/F1'): font})})
    commands, y = [], 742
    for size, text in lines:
        escaped = text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
        commands.append(f'BT /F1 {size} Tf 48 {y} Td ({escaped}) Tj ET')
        y -= max(20, size + 10)
    stream = DecodedStreamObject()
    stream.set_data('\n'.join(commands).encode('ascii'))
    page.replace_contents(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()
