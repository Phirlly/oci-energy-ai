"""Invented public examples, intentionally independent of customer documents."""

EXAMPLES = [
    """FICTIONAL DEMO - Juniper Power
Electricity service / Account DEMO-A71 / Meter MTR-EXAMPLE
Service dates 2024-02-01 to 2024-03-01; 29 days
Imported consumption: 580 kWh. Currency: USD.
Current electricity charges: 91.50
Energy including service fee: 90.00
Included service fee: 12.00 (already in Energy)
Tax: 3.00
Energy credit: -1.50
Previous balance: 40.00
Amount due: 131.50""",
    """FICTIONAL DEMO / Cedar Municipal Utilities
Customer account: SAMPLE-B82   Electric meter: LAB-001
USD statement
Reading dates: April 10, 2024 - May 10, 2024
Billing days: 30
ELECTRICITY | Imported energy (kWh) | 900
Energy charge 108.00
Service charge 15.00
Electricity tax 6.15
TOTAL CURRENT ELECTRICITY 129.15
Payments received -100.00
Previous balance 110.00
TOTAL ACCOUNT DUE 139.15""",
    """FICTIONAL DEMO / Willow Water District
Account WATER-DEMO / Meter WATER-ONLY
2024-05-01 through 2024-05-31 (31 days)
Water supplied: 4200 gallons
Water service USD 32.00; sewer USD 18.00
Current water and sewer charges USD 50.00.
Community notice: report electrical outages to your electricity provider.
This statement contains no electricity service."""
]

EXAMPLE_FACTS = {
    "supplier": "Juniper Power", "account": "DEMO-A71", "meter": "MTR-EXAMPLE",
    "service": "electricity", "usage_kind": "consumption", "unit": "kWh",
    "period_start": "2024-02-01", "period_end": "2024-03-01", "days": 29,
    "currency": "USD", "consumption": "580", "current_total": "91.50",
    "charges": [
        {"label": "Energy including service fee", "amount": "90", "role": "additive"},
        {"label": "Included service fee", "amount": "12", "role": "included"},
        {"label": "Tax", "amount": "3", "role": "additive"},
        {"label": "Energy credit", "amount": "-1.50", "role": "additive"},
        {"label": "Previous balance", "amount": "40", "role": "excluded"},
    ],
}
