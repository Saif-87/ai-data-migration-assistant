"""The target structure: what each booking should look like after cleaning.

This file only describes the fields and their rules. cleaning.py does the actual
fixing and checking, and mapping.py sends these descriptions to the AI so it
understands what each field means.

The field names match the Airtable table exactly, so they can be sent straight to it.
"""

from dataclasses import dataclass

# The only allowed status values. Kept as a list so cleaning.py can check against it.
STATUS_VALUES = ["Confirmed", "Pending", "Cancelled"]


# A Field describes one column in the clean table.
# @dataclass is a shortcut: Python writes the setup code (__init__) for us.
@dataclass
class Field:
    name: str          # column name in the target system (Airtable)
    type: str          # "text", "date" or "number"
    required: bool     # must every record have a value?
    description: str   # plain-English meaning, shown to the AI
    format_rule: str   # how a clean value must look


# The 8 target fields. The descriptions are written for the AI, so keep them clear.
# The examples (e.g. ...) help the AI understand the format.
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
        format_rule="Exactly one of: Confirmed, Pending, Cancelled.",
    ),
]

# Rules that compare two fields. They can't live inside one Field, so they're kept here.
CROSS_FIELD_RULES = [
    {
        "name": "travel_after_booking",
        "fields": ["booking_date", "travel_date"],
        "description": "travel_date must be after booking_date.",
    },
]

# A list of just the field names: ["customer_name", "email", ...]
FIELD_NAMES = []
for field in FIELDS:
    FIELD_NAMES.append(field.name)

# A list of the fields that can't be empty.
REQUIRED_FIELDS = []
for field in FIELDS:
    if field.required:
        REQUIRED_FIELDS.append(field.name)
