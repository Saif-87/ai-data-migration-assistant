"""Send clean booking rows to the Airtable table "Bookings".

Run:  python migrate.py   (test: sends only the first 3 clean rows of the sample file)

Uses the Airtable REST API directly with the requests library. Every row's
result (migrated or failed) is written to the migration_log table in
migration.db, so there is a record of what happened in each run.
"""

import os
import sqlite3
import time
from datetime import datetime

import requests
from dotenv import load_dotenv

from cleaning import is_blank
from database import DB_FILE, create_migration_log
from schema import FIELDS

TABLE_NAME = "Bookings"
API_URL = "https://api.airtable.com/v0"

# Airtable accepts at most 10 records in one request.
BATCH_SIZE = 10

# Airtable allows 5 requests per second. A short pause between batches keeps us under that.
PAUSE_SECONDS = 0.25


def row_to_airtable_fields(row):
    """Turn one clean row into the "fields" Airtable expects.

    Empty optional fields are left out instead of being sent as blanks,
    so Airtable keeps them empty rather than storing an empty text.
    """
    fields = {}
    for field in FIELDS:
        value = row[field.name]

        if is_blank(value):
            continue  # leave this field out

        if field.type == "number":
            fields[field.name] = float(value)   # amount_aed is sent as a number, e.g. 1200.0
        else:
            fields[field.name] = str(value)     # text and dates (already YYYY-MM-DD) are sent as text

    return fields


def get_error_message(response):
    """Pull a readable error message out of Airtable's reply."""
    # Airtable usually replies like: {"error": {"type": "...", "message": "..."}}
    try:
        data = response.json()
    except ValueError:
        return f"Airtable error {response.status_code}: {response.text[:200]}"

    error = data.get("error")
    if isinstance(error, dict):
        error_type = error.get("type", "")
        error_message = error.get("message", "")
        return f"Airtable error {response.status_code} ({error_type}): {error_message}"

    # Sometimes the error is just a word, e.g. {"error": "NOT_FOUND"}
    return f"Airtable error {response.status_code}: {error}"


def send_batch(url, headers, batch):
    """Send up to 10 rows to Airtable in one request.

    Returns None if it worked, or an error message if it failed.
    """
    records = []
    for row in batch:
        records.append({"fields": row_to_airtable_fields(row)})

    try:
        response = requests.post(url, headers=headers, json={"records": records}, timeout=30)
    except requests.RequestException as error:
        # No internet, timeout, etc. The message never contains the token (it's only in the headers).
        return f"Could not reach Airtable: {error}"

    if response.status_code == 200:
        return None
    return get_error_message(response)


def log_results(run_id, batch, result, reason):
    """Write one line per row into the migration_log table."""
    conn = sqlite3.connect(DB_FILE)
    create_migration_log(conn)  # makes sure the table exists
    for row in batch:
        conn.execute(
            "INSERT INTO migration_log (run_id, row_number, customer_name, result, reason) "
            "VALUES (?, ?, ?, ?, ?)",
            (run_id, int(row["row_number"]), row["customer_name"], result, reason),
        )
    conn.commit()
    conn.close()


def migrate(clean_rows, on_progress=None):
    """Send clean rows to Airtable in batches of 10.

    clean_rows:  the clean_rows DataFrame from cleaning.clean_and_validate()
    on_progress: optional function called after each batch as on_progress(rows_done, total_rows),
                 used by app.py to move the progress bar

    Returns a summary dict:
        run_id, migrated, failed, failed_rows (list of row_number, customer_name, reason),
        error (a message if the migration couldn't start at all, otherwise None)
    """
    # Each run gets its own id, e.g. "run-20261009-143005", so its log lines can be found later.
    run_id = datetime.now().strftime("run-%Y%m%d-%H%M%S")

    summary = {
        "run_id": run_id,
        "migrated": 0,
        "failed": 0,
        "failed_rows": [],
        "error": None,
    }

    # Read the Airtable settings from .env. The token is never printed or logged.
    load_dotenv()
    token = os.getenv("AIRTABLE_TOKEN")
    base_id = os.getenv("AIRTABLE_BASE_ID")
    if not token or not base_id:
        summary["error"] = "AIRTABLE_TOKEN or AIRTABLE_BASE_ID is not set. Add them to your .env file."
        return summary

    url = f"{API_URL}/{base_id}/{TABLE_NAME}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # Turn the table into a list of rows, e.g. [{"row_number": 1, "customer_name": "...", ...}, ...]
    rows = clean_rows.to_dict(orient="records")
    total = len(rows)

    # Go through the rows 10 at a time: rows 0-9, then 10-19, and so on.
    for start in range(0, total, BATCH_SIZE):
        batch = rows[start:start + BATCH_SIZE]

        error_message = send_batch(url, headers, batch)

        if error_message is None:
            summary["migrated"] = summary["migrated"] + len(batch)
            log_results(run_id, batch, "migrated", None)
        else:
            # WHY: don't stop on a failed batch. Record it and carry on with the next one,
            # so one bad batch doesn't block all the other rows.
            summary["failed"] = summary["failed"] + len(batch)
            log_results(run_id, batch, "failed", error_message)
            for row in batch:
                failed_row = {
                    "row_number": int(row["row_number"]),
                    "customer_name": row["customer_name"],
                    "reason": error_message,
                }
                summary["failed_rows"].append(failed_row)

        rows_done = start + len(batch)
        if on_progress is not None:
            on_progress(rows_done, total)

        # Pause before the next batch (not needed after the last one).
        if rows_done < total:
            time.sleep(PAUSE_SECONDS)

    return summary


if __name__ == "__main__":
    import pandas as pd

    from cleaning import clean_and_validate

    # Same hand-written mapping as in cleaning.py's test.
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
    clean_rows, flagged_rows, cleaning_summary = clean_and_validate(df)

    # Test with only the first 3 clean rows, so we don't fill Airtable while testing.
    test_rows = clean_rows.head(3)
    print(f"Sending {len(test_rows)} clean rows to Airtable table '{TABLE_NAME}'...\n")

    summary = migrate(test_rows)

    if summary["error"] is not None:
        print(f"Error: {summary['error']}")
    else:
        print(f"Run id:   {summary['run_id']}")
        print(f"Migrated: {summary['migrated']}")
        print(f"Failed:   {summary['failed']}")
        for failed_row in summary["failed_rows"]:
            print(f"  row {failed_row['row_number']} ({failed_row['customer_name']}): {failed_row['reason']}")
