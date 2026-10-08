"""Create a synthetic, deliberately messy booking spreadsheet.

Run:  python generate_data.py
Output: sample_data/messy_bookings.csv (about 100 rows)

All data is fake (made with Faker). The mess is added on purpose so the
cleaning and mapping steps have realistic problems to solve.
"""

import csv
import random
from datetime import date, timedelta
from pathlib import Path

from faker import Faker

# Fixed seeds so the same "messy" file is produced every run.
SEED = 42
random.seed(SEED)
Faker.seed(SEED)
fake = Faker(["en_GB", "en_IN"])

OUTPUT_FILE = Path("sample_data") / "messy_bookings.csv"
UNIQUE_BOOKINGS = 92
DUPLICATE_BOOKINGS = 8  # 92 + 8 = 100 rows

# Problem 1: inconsistent column names (mixed case, spaces, underscores, abbreviations).
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


# Problem 2: mixed date formats.
def messy_date(d):
    style = random.choice(["slash", "iso", "short"])
    if style == "slash":
        return d.strftime("%d/%m/%Y")         # 03/10/2026
    if style == "iso":
        return d.strftime("%Y-%m-%d")         # 2026-10-03
    day = str(d.day)                          # "3", no leading zero
    month_year = d.strftime("%b %y")          # "Oct 26"
    return day + " " + month_year             # 3 Oct 26


# Problem 5a: prices written in different ways.
def messy_price(amount):
    style = random.choice(["aed", "plain", "k"])
    if style == "aed":
        return f"AED {amount:,}"              # AED 1,200
    if style == "plain":
        return str(amount)                    # 1200
    thousands = amount / 1000                 # 1200 -> 1.2, 5000 -> 5.0
    if thousands.is_integer():
        thousands = int(thousands)            # 5.0 -> 5, so we get "5k" not "5.0k"
    return str(thousands) + "k"               # 1.2k


# Problem 5b: UAE phone numbers with and without the country code.
def messy_phone():
    prefix = random.choice(["50", "52", "55", "56"])
    rest = str(random.randint(0, 9999999)).zfill(7)  # zfill pads with zeros on the left: 42 -> "0000042"
    style = random.choice(["plus", "zeros", "local", "bare"])
    if style == "plus":
        return f"+971 {prefix} {rest[:3]} {rest[3:]}"   # +971 50 123 4567
    if style == "zeros":
        return f"00971{prefix}{rest}"                    # 00971501234567
    if style == "local":
        return f"0{prefix} {rest[:3]} {rest[3:]}"        # 050 123 4567
    return f"{prefix}{rest}"                             # 501234567


# Problem 3: the same customer typed slightly differently.
def misspell(name):
    style = random.choice(["lower", "upper", "spaces", "drop_letter", "swap_letters"])
    if style == "lower":
        return name.lower()
    if style == "upper":
        return name.upper()
    if style == "spaces":
        return "  " + name.replace(" ", "  ") + " "
    i = random.randint(1, len(name) - 3)
    if style == "drop_letter":
        return name[:i] + name[i + 1:]
    before = name[:i]
    first_letter = name[i]
    second_letter = name[i + 1]
    after = name[i + 2:]
    return before + second_letter + first_letter + after   # swap two letters


def make_booking():
    first, last = fake.first_name(), fake.last_name()
    booking_date = fake.date_between(start_date=date(2026, 1, 1), end_date=date(2026, 9, 30))
    travel_date = booking_date + timedelta(days=random.randint(7, 180))
    amount = random.randint(5, 150) * 100  # whole hundreds, so "1.2k" style is exact

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

    # Problem 4: missing values.
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

    # Duplicates: repeat some customers with a misspelled name but the same contact details.
    for booking in random.sample(bookings, DUPLICATE_BOOKINGS):
        rows.append(to_row(booking, misspell(booking["name"])))

    random.shuffle(rows)  # so duplicates aren't all at the bottom

    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
