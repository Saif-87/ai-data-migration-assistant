"""Target schema: the clean structure bookings must have after migration.

This file only *describes* the target fields and their rules. The code that
enforces the rules lives in cleaning.py. The descriptions are also sent to the
LLM in mapping.py so it knows what each target field means.

Field names match the Airtable table exactly.
"""

from dataclasses import dataclass

STATUS_VALUES = ["Confirmed", "Pending", "Cancelled"]


@dataclass(frozen=True)
class Field:
    name: str          # column name in the target system (Airtable)
    type: str          # "text", "date" or "number"
    required: bool     # must every record have a value?
    description: str   # plain-English meaning, shown to the LLM
    format_rule: str   # how a clean value must look


FIELDS = [
    Field(
        name="customer_name",
        type="text",
        required=True,
        description="Full name of the customer who made the booking.",
        format_rule="Title case, single spaces, no leading or trailing spaces (e.g. 'Aimee Khare').",
    ),
    Field(
        name="email",
        type="text",
        required=False,
        description="The customer's email address for booking confirmations.",
        format_rule="Valid email format, all lowercase (e.g. 'aimee.khare@outlook.com').",
    ),
    Field(
        name="phone",
        type="text",
        required=False,
        description="The customer's contact phone number.",
        format_rule="International format: '+', country code, then digits, no spaces (e.g. '+971501234567').",
    ),
    Field(
        name="destination",
        type="text",
        required=True,
        description="The city or place the customer is travelling to.",
        format_rule="Plain text place name (e.g. 'Paris').",
    ),
    Field(
        name="booking_date",
        type="date",
        required=False,
        description="The date the booking was made.",
        format_rule="YYYY-MM-DD (e.g. '2026-10-03').",
    ),
    Field(
        name="travel_date",
        type="date",
        required=False,
        description="The date the customer departs on the trip.",
        format_rule="YYYY-MM-DD (e.g. '2026-11-15'), and after booking_date.",
    ),
    Field(
        name="amount_aed",
        type="number",
        required=False,
        description="Total price of the booking in UAE dirhams (AED).",
        format_rule="A positive number with no currency text or commas (e.g. 1200).",
    ),
    Field(
        name="status",
        type="text",
        required=False,
        description="Current state of the booking.",
        format_rule="Exactly one of: " + ", ".join(STATUS_VALUES) + ".",
    ),
]

# Rules that compare two fields, so they can't belong to a single Field.
CROSS_FIELD_RULES = [
    {
        "name": "travel_after_booking",
        "fields": ["booking_date", "travel_date"],
        "description": "travel_date must be after booking_date.",
    },
]

# Handy lookups.
FIELDS_BY_NAME = {field.name: field for field in FIELDS}
FIELD_NAMES = [field.name for field in FIELDS]
REQUIRED_FIELDS = [field.name for field in FIELDS if field.required]
