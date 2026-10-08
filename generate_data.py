"""Make a fake, messy spreadsheet of travel bookings.

Run:  python generate_data.py
Output: sample_data/messy_bookings.csv (100 rows)

Every name, email and phone number is made up using the Faker library.
The data is made messy on purpose, like a real spreadsheet typed by hand,
so the rest of the project has real problems to clean up.
"""

import csv
import random
from datetime import date, timedelta
from pathlib import Path

from faker import Faker

# Using the same seed every time means we get the exact same "random" file on every run.
# That way test results don't change from one run to the next.
SEED = 42
random.seed(SEED)
Faker.seed(SEED)

# British and Indian names, a realistic mix of customers for a travel agency in the UAE.
fake = Faker(["en_GB", "en_IN"])

OUTPUT_FILE = Path("sample_data") / "messy_bookings.csv"
UNIQUE_BOOKINGS = 92
DUPLICATE_BOOKINGS = 8  # 92 + 8 = 100 rows

# Column names written in different styles (spaces, dots, capitals, short forms),
# the way they often look in an old spreadsheet.
COLUMNS = [
    "Cust Name",
    "E-mail",
    "phone_no",
    "Dest.",
    "Booked On",
    "travel dt",
    "Price",
    "STATUS",
]

DESTINATIONS = [
    "Paris", "London", "Bali", "Maldives", "Istanbul", "Tokyo",
    "Singapore", "Cairo", "Baku", "Tbilisi", "Phuket", "Zurich",
]
STATUSES = ["Confirmed", "Pending", "Cancelled"]


def messy_date(d):
    """Write a date in one of three styles, picked at random."""
    style = random.choice(["slash", "iso", "short"])
    if style == "slash":
        return d.strftime("%d/%m/%Y")         # 03/10/2026
    if style == "iso":
        return d.strftime("%Y-%m-%d")         # 2026-10-03
    day = str(d.day)                          # "3", no leading zero
    month_year = d.strftime("%b %y")          # "Oct 26"
    return day + " " + month_year             # 3 Oct 26


def messy_price(amount):
    """Write a price in one of three styles, picked at random."""
    style = random.choice(["aed", "plain", "k"])
    if style == "aed":
        return f"AED {amount:,}"              # AED 1,200  (the "," adds a thousands comma)
    if style == "plain":
        return str(amount)                    # 1200
    thousands = amount / 1000                 # 1200 -> 1.2, 5000 -> 5.0
    if thousands.is_integer():
        thousands = int(thousands)            # 5.0 -> 5, so we get "5k" not "5.0k"
    return str(thousands) + "k"               # 1.2k


def messy_phone():
    """Make a UAE mobile number, written with or without the country code (+971)."""
    prefix = random.choice(["50", "52", "55", "56"])  # real UAE mobile prefixes
    rest = str(random.randint(0, 9999999)).zfill(7)  # zfill pads with zeros on the left: 42 -> "0000042"
    style = random.choice(["plus", "zeros", "local", "bare"])
    if style == "plus":
        return f"+971 {prefix} {rest[:3]} {rest[3:]}"   # +971 50 123 4567
    if style == "zeros":
        return f"00971{prefix}{rest}"                    # 00971501234567
    if style == "local":
        return f"0{prefix} {rest[:3]} {rest[3:]}"        # 050 123 4567
    return f"{prefix}{rest}"                             # 501234567


def misspell(name):
    """Change a name slightly, like someone typing the same customer twice."""
    style = random.choice(["lower", "upper", "spaces", "drop_letter", "swap_letters"])
    if style == "lower":
        return name.lower()                              # aimee khare
    if style == "upper":
        return name.upper()                              # AIMEE KHARE
    if style == "spaces":
        return "  " + name.replace(" ", "  ") + " "      # "  Aimee  Khare "

    # Pick a letter position to change. We start at 1 so the first letter stays correct,
    # and stop 3 before the end so there is always a next letter to swap with.
    i = random.randint(1, len(name) - 3)
    if style == "drop_letter":
        return name[:i] + name[i + 1:]                   # Aime Khare
    before = name[:i]
    first_letter = name[i]
    second_letter = name[i + 1]
    after = name[i + 2:]
    return before + second_letter + first_letter + after   # Aimee Kahre


def make_booking():
    """Make one correct booking. The mess is added later, in to_row()."""
    first, last = fake.first_name(), fake.last_name()
    booking_date = fake.date_between(start_date=date(2026, 1, 1), end_date=date(2026, 9, 30))

    # Travel is always 7 to 180 days after booking, so this date is never wrong.
    # The only problems in the file are the ones we add on purpose.
    travel_date = booking_date + timedelta(days=random.randint(7, 180))

    # Prices are whole hundreds (500, 1200 ...), so "1.2k" is always exact.
    amount = random.randint(5, 150) * 100

    return {
        "name": f"{first} {last}",
        "email": f"{first}.{last}@{fake.free_email_domain()}".lower(),
        "phone": messy_phone(),
        "destination": random.choice(DESTINATIONS),
        "booking_date": booking_date,
        "travel_date": travel_date,
        "amount": amount,
        "status": random.choice(STATUSES),
    }


def to_row(booking, name):
    """Turn a booking into one spreadsheet row, with messy dates and prices."""
    row = {
        "Cust Name": name,
        "E-mail": booking["email"],
        "phone_no": booking["phone"],
        "Dest.": booking["destination"],
        "Booked On": messy_date(booking["booking_date"]),
        "travel dt": messy_date(booking["travel_date"]),
        "Price": messy_price(booking["amount"]),
        "STATUS": booking["status"],
    }

    # Leave some cells empty: about 1 in 10 emails and 1 in 12 booking dates.
    if random.random() < 0.10:
        row["E-mail"] = ""
    if random.random() < 0.08:
        row["Booked On"] = ""

    return row


def main():
    bookings = []
    for _ in range(UNIQUE_BOOKINGS):
        bookings.append(make_booking())

    rows = []
    for booking in bookings:
        rows.append(to_row(booking, booking["name"]))

    # Add duplicates: the same customer again, with a slightly different name
    # but the same email and phone, so they can be spotted later.
    # We call to_row() again instead of copying the row, so the copy gets its own
    # date and price styles, just like a second booking typed in by hand.
    for booking in random.sample(bookings, DUPLICATE_BOOKINGS):
        rows.append(to_row(booking, misspell(booking["name"])))

    # Mix up the order, otherwise all the duplicates would sit at the bottom of the file.
    random.shuffle(rows)

    OUTPUT_FILE.parent.mkdir(exist_ok=True)  # create the sample_data folder if it doesn't exist
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
