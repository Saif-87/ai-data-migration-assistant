"""Clean and validate booking rows against the target schema.

Run:  python cleaning.py

The DataFrame passed in must already use the target field names from
schema.py (after AI mapping and human confirmation). Values are fixed
automatically where possible. Rows with problems that can't be fixed are
flagged with a plain-English reason, never silently dropped.
"""

from datetime import datetime
from difflib import SequenceMatcher

import pandas as pd

from schema import FIELD_NAMES, REQUIRED_FIELDS, STATUS_VALUES

# Fields every row must have.
# booking_date is optional in schema.py, but we need it to check travel_date, so we add it here.
MUST_HAVE_FIELDS = REQUIRED_FIELDS + ["booking_date"]

# Date formats we understand, e.g. 03/10/2026, 2026-10-03, 3 Oct 26
DATE_FORMATS = ["%d/%m/%Y", "%Y-%m-%d", "%d %b %y"]

# How alike two names must be (0 to 1) to count as the same person.
NAME_SIMILARITY = 0.85


# ---------- Cleaning functions ----------
# Each one returns the clean value, or None if the value is blank or can't be understood.

def is_blank(value):
    """True if the cell is empty (None, NaN or only spaces)."""
    if value is None or pd.isna(value):
        return True
    return str(value).strip() == ""


def clean_text(value):
    """Remove spaces at the start and end, and turn double spaces into single spaces."""
    if is_blank(value):
        return None
    words = str(value).split()  # split() also throws away extra spaces
    return " ".join(words)


def clean_name(value):
    """'  aimee  KHARE ' -> 'Aimee Khare'"""
    text = clean_text(value)
    if text is None:
        return None
    return text.title()


def clean_email(value):
    """' Aimee@Mail.com ' -> 'aimee@mail.com'"""
    text = clean_text(value)
    if text is None:
        return None
    return text.lower()


def clean_phone(value):
    """Convert a UAE number to +971XXXXXXXXX.

    "+971 50 123 4567" -> "+971501234567"
    "00971501234567"   -> "+971501234567"
    "050 123 4567"     -> "+971501234567"
    "501234567"        -> "+971501234567"
    """
    if is_blank(value):
        return None

    # Keep only the digits: "+971 50 123 4567" -> "971501234567"
    digits = ""
    for character in str(value):
        if character.isdigit():
            digits = digits + character

    # Remove the country code or leading zero, so only the 9-digit local number is left.
    if digits.startswith("00971") and len(digits) == 14:
        digits = digits[5:]
    elif digits.startswith("971") and len(digits) == 12:
        digits = digits[3:]
    elif digits.startswith("0") and len(digits) == 10:
        digits = digits[1:]

    # A UAE local number has 9 digits. Anything else we can't fix.
    if len(digits) != 9:
        return None
    return "+971" + digits


def clean_date(value):
    """Try each known format. '3 Oct 26' -> '2026-10-03'"""
    text = clean_text(value)
    if text is None:
        return None

    for date_format in DATE_FORMATS:
        try:
            date = datetime.strptime(text, date_format)
            return date.strftime("%Y-%m-%d")
        except ValueError:
            pass  # this format didn't match, try the next one

    return None  # no format matched


def clean_amount(value):
    """'AED 1,200', '1200' and '1.2k' -> 1200.0"""
    text = clean_text(value)
    if text is None:
        return None

    text = text.upper()
    text = text.replace("AED", "")
    text = text.replace(",", "")
    text = text.strip()

    # "1.2K" means 1.2 x 1000
    multiplier = 1
    if text.endswith("K"):
        multiplier = 1000
        text = text[:-1]  # remove the "K"

    try:
        number = float(text)
    except ValueError:
        return None  # not a number, e.g. "free"

    return round(number * multiplier, 2)


def clean_status(value):
    """' confirmed ' -> 'Confirmed'. Returns None if it isn't an allowed status."""
    text = clean_text(value)
    if text is None:
        return None

    for status in STATUS_VALUES:
        if text.lower() == status.lower():
            return status
    return None


def is_valid_email(email):
    """Simple check: one @, something before it, and a dot after it. No spaces."""
    if " " in email or email.count("@") != 1:
        return False
    before, after = email.split("@")
    return before != "" and "." in after and not after.startswith(".") and not after.endswith(".")


# Which cleaning function to use for each field.
CLEANERS = {
    "customer_name": clean_name,
    "email": clean_email,
    "phone": clean_phone,
    "destination": clean_text,
    "booking_date": clean_date,
    "travel_date": clean_date,
    "amount_aed": clean_amount,
    "status": clean_status,
}

# Reason shown when a field has a value but its cleaner can't understand it.
UNREADABLE_REASON = {
    "phone": "unreadable phone",
    "booking_date": "unreadable booking_date",
    "travel_date": "unreadable travel_date",
    "amount_aed": "amount not a number",
    "status": "invalid status",
}


# ---------- Duplicate helpers ----------

def normalise_name(name):
    """Lowercase and remove all spaces: 'AIMEE  KHARE' -> 'aimeekhare'"""
    return str(name).lower().replace(" ", "")


def similar_names(name1, name2):
    """True if two names are nearly the same (allows a missing or swapped letter)."""
    similarity = SequenceMatcher(None, name1, name2).ratio()  # 1.0 = identical
    return similarity >= NAME_SIMILARITY


def as_text(value):
    """Show a value the way it looks in a spreadsheet, so we can tell if cleaning changed it."""
    if is_blank(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))  # 1200.0 -> "1200"
    return str(value)


# ---------- Main function ----------

def clean_and_validate(df):
    """Clean every row, then flag rows with problems.

    Returns (clean_rows, flagged_rows, summary):
    - clean_rows:   DataFrame of rows with no problems, ready to migrate
    - flagged_rows: DataFrame of rows needing human review, with an "issues" column
    - summary:      dict of counts (rows, values cleaned per field, flags per reason)
    Both DataFrames have a row_number column (1 = first data row of the source).
    """
    original = df.copy().reset_index(drop=True)

    # If a target field wasn't mapped, add it as an empty column.
    for field in FIELD_NAMES:
        if field not in original.columns:
            original[field] = None

    number_of_rows = len(original)

    # The cleaned table starts with a row number (1, 2, 3 ...) so people can find the original row.
    cleaned = pd.DataFrame()
    cleaned["row_number"] = range(1, number_of_rows + 1)

    # issues[i] is a list of (reason, message) problems found in row i.
    issues = []
    for i in range(number_of_rows):
        issues.append([])

    # ----- Step 1: clean each field -----
    values_cleaned = {}  # field -> how many values cleaning changed

    for field in FIELD_NAMES:
        cleaner = CLEANERS[field]
        new_values = []
        changed = 0

        for i in range(number_of_rows):
            raw = original.at[i, field]
            value = cleaner(raw)

            if value is None and not is_blank(raw):
                # There was something in the cell, but we couldn't understand it.
                message = f"{field} '{raw}' could not be understood."
                issues[i].append((UNREADABLE_REASON[field], message))
            elif as_text(value) != as_text(raw):
                changed = changed + 1

            new_values.append(value)

        cleaned[field] = new_values
        values_cleaned[field] = changed

    # ----- Step 2: check each row -----
    for i in range(number_of_rows):
        email = cleaned.at[i, "email"]
        booking_date = cleaned.at[i, "booking_date"]
        travel_date = cleaned.at[i, "travel_date"]
        amount = cleaned.at[i, "amount_aed"]

        # Must-have fields are empty
        for field in MUST_HAVE_FIELDS:
            if is_blank(original.at[i, field]):
                issues[i].append((f"missing {field}", f"{field} is missing."))

        # Email is filled in but doesn't look like an email
        if not is_blank(email) and not is_valid_email(email):
            message = f"email '{email}' is not a valid email address."
            issues[i].append(("invalid email", message))

        # Travel date is on or before booking date (YYYY-MM-DD text sorts like dates)
        if not is_blank(booking_date) and not is_blank(travel_date):
            if travel_date <= booking_date:
                message = f"travel_date {travel_date} is not after booking_date {booking_date}."
                issues[i].append(("travel_date not after booking_date", message))

        # Amount is empty, or zero / negative
        if is_blank(original.at[i, "amount_aed"]):
            issues[i].append(("amount missing", "amount_aed is missing."))
        elif not is_blank(amount) and amount <= 0:
            issues[i].append(("amount not positive", f"amount_aed {amount} is not positive."))

    # ----- Step 3: find likely duplicates -----
    # Same person = similar name AND same email or same phone.
    # The first row is kept; later copies are flagged.
    kept_rows = []  # rows we've seen that are not duplicates

    for i in range(number_of_rows):
        name = cleaned.at[i, "customer_name"]
        email = cleaned.at[i, "email"]
        phone = cleaned.at[i, "phone"]

        if is_blank(name):
            continue  # can't compare without a name

        is_duplicate = False

        for j in kept_rows:
            same_email = not is_blank(email) and email == cleaned.at[j, "email"]
            same_phone = not is_blank(phone) and phone == cleaned.at[j, "phone"]
            same_name = similar_names(normalise_name(name), normalise_name(cleaned.at[j, "customer_name"]))

            if (same_email or same_phone) and same_name:
                first_name = cleaned.at[j, "customer_name"]
                message = f"Likely duplicate of row {j + 1} ({first_name})."
                issues[i].append(("likely duplicate", message))
                is_duplicate = True
                break  # one match is enough

        if not is_duplicate:
            kept_rows.append(i)

    # ----- Step 4: split into clean rows and flagged rows -----
    issue_text = []
    for row_issues in issues:
        messages = [message for reason, message in row_issues]
        issue_text.append("; ".join(messages))  # "" if the row has no problems
    cleaned["issues"] = issue_text

    flagged_rows = cleaned[cleaned["issues"] != ""].reset_index(drop=True)
    clean_rows = cleaned[cleaned["issues"] == ""].drop(columns="issues").reset_index(drop=True)

    # Count how many times each reason was flagged.
    flagged_by_reason = {}
    for row_issues in issues:
        for reason, message in row_issues:
            flagged_by_reason[reason] = flagged_by_reason.get(reason, 0) + 1

    summary = {
        "total_rows": number_of_rows,
        "clean_rows": len(clean_rows),
        "flagged_rows": len(flagged_rows),
        "values_cleaned": values_cleaned,
        "flagged_by_reason": flagged_by_reason,
    }
    return clean_rows, flagged_rows, summary


if __name__ == "__main__":
    # In app.py a person confirms this mapping. Here it's written out by hand for testing.
    COLUMN_MAPPING = {
        "Cust Name": "customer_name",
        "E-mail": "email",
        "phone_no": "phone",
        "Dest.": "destination",
        "Booked On": "booking_date",
        "travel dt": "travel_date",
        "Price": "amount_aed",
        "STATUS": "status",
    }

    df = pd.read_csv("sample_data/messy_bookings.csv", dtype=str)
    df = df.rename(columns=COLUMN_MAPPING)

    clean_rows, flagged_rows, summary = clean_and_validate(df)

    print(f"Rows: {summary['total_rows']} total, {summary['clean_rows']} clean, "
          f"{summary['flagged_rows']} flagged\n")

    print("Values changed by cleaning:")
    for field, count in summary["values_cleaned"].items():
        print(f"  {field:<14} {count}")  # :<14 pads the name so the numbers line up

    print("\nFlags by reason (a row can have more than one):")
    for reason, count in summary["flagged_by_reason"].items():
        print(f"  {reason:<36} {count}")

    pd.set_option("display.width", 200)  # stop pandas wrapping wide tables
    print("\nFirst 5 clean rows:")
    print(clean_rows.head(5).to_string(index=False))

    print("\nFlagged rows:")
    print(flagged_rows[["row_number", "customer_name", "issues"]].to_string(index=False))
