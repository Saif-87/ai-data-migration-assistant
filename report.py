"""Build the migration report for one run.

Run:  python report.py   (builds a report for the latest run in migration_log)

The report comes in two forms:
- Markdown text: a readable summary to show on the page or save as a .md file
- CSV text: one line per record (customer name, result, reason) to open in a spreadsheet

The migrated / failed numbers come from the migration_log table in migration.db,
so the report shows what was really recorded, not what we hoped happened.
"""

import sqlite3

import pandas as pd

from database import DB_FILE

# Plain-English names for what cleaning did to each field.
CLEANING_LABELS = {
    "customer_name": "Names tidied (spaces, capital letters)",
    "email": "Emails trimmed and lowercased",
    "phone": "Phone numbers converted to +971 format",
    "destination": "Destinations tidied (spaces)",
    "booking_date": "Booking dates reformatted to YYYY-MM-DD",
    "travel_date": "Travel dates reformatted to YYYY-MM-DD",
    "amount_aed": "Prices converted to numbers",
    "status": "Statuses fixed (capital letters, spaces)",
}


# ---------- Reading the migration_log table ----------

def count_results(conn, run_id):
    """Count how many rows of one run were migrated and how many failed.

    Run ONE SQL query on the migration_log table, only for rows with this run_id,
    that counts the rows for each result (GROUP BY result).

    Returns a dictionary that always has both keys, e.g.
        {"migrated": 84, "failed": 2}
    If a result doesn't appear in the log (for example nothing failed), its count is 0:
        {"migrated": 3, "failed": 0}
    """
    # WHY: start both at 0, because if nothing failed the query returns no "failed" row at all.
    counts = {"migrated": 0, "failed": 0}

    rows = conn.execute(
        """
        SELECT result, COUNT(*) AS times
        FROM migration_log
        WHERE run_id = ?
        GROUP BY result
        """,
        (run_id,),
    ).fetchall()

    # rows looks like [("migrated", 84), ("failed", 2)]
    for result, times in rows:
        counts[result] = times

    return counts


def get_failure_reasons(conn, run_id):
    """Return each failure reason and how many rows failed for it, e.g. [("Airtable error 422 ...", 10)]."""
    return conn.execute(
        """
        SELECT reason, COUNT(*) AS times
        FROM migration_log
        WHERE run_id = ? AND result = 'failed'
        GROUP BY reason
        ORDER BY times DESC
        """,
        (run_id,),
    ).fetchall()


def get_run_details(conn, run_id):
    """Return one line per row sent in this run: (row_number, customer_name, result, reason)."""
    return conn.execute(
        """
        SELECT row_number, customer_name, result, reason
        FROM migration_log
        WHERE run_id = ?
        ORDER BY row_number
        """,
        (run_id,),
    ).fetchall()


def get_run_time(conn, run_id):
    """Return when the run was logged, e.g. "2026-10-09 00:16:49" (UTC)."""
    row = conn.execute(
        "SELECT MIN(logged_at) FROM migration_log WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    return row[0]


def get_latest_run_id(conn):
    """Return the run_id of the most recent run, or None if nothing has been migrated yet."""
    # rowid is the order lines were added, so the highest rowid is the newest line.
    row = conn.execute("SELECT run_id FROM migration_log ORDER BY rowid DESC LIMIT 1").fetchone()
    if row is None:
        return None
    return row[0]


# ---------- Building the report ----------

def build_markdown(run_id, run_time, mapping, cleaning_summary, counts, failure_reasons):
    """Put all the numbers together as Markdown text."""
    lines = []

    lines.append("# Migration report")
    lines.append("")
    lines.append(f"- **Run id:** {run_id}")
    lines.append(f"- **Date and time:** {run_time} (UTC)")
    lines.append("")

    # Summary numbers
    lines.append("## Summary")
    lines.append("")
    lines.append("| | Records |")
    lines.append("|---|---|")
    lines.append(f"| Records in source file | {cleaning_summary['total_rows']} |")
    lines.append(f"| Clean rows | {cleaning_summary['clean_rows']} |")
    lines.append(f"| Flagged for review (not migrated) | {cleaning_summary['flagged_rows']} |")
    lines.append(f"| Migrated to Airtable | {counts['migrated']} |")
    lines.append(f"| Failed | {counts['failed']} |")

    # WHY: if only some clean rows were sent (e.g. a test run), say so, so the numbers add up.
    not_sent = cleaning_summary["clean_rows"] - counts["migrated"] - counts["failed"]
    if not_sent > 0:
        lines.append(f"| Clean rows not sent in this run | {not_sent} |")
    lines.append("")

    # Mapping
    lines.append("## Fields mapped")
    lines.append("")
    lines.append("| Source column | Target field |")
    lines.append("|---|---|")
    for source_column, target_field in mapping.items():
        lines.append(f"| {source_column} | {target_field} |")
    lines.append("")

    # Cleaning
    lines.append("## What was cleaned")
    lines.append("")
    lines.append("| Change | Values |")
    lines.append("|---|---|")
    for field, count in cleaning_summary["values_cleaned"].items():
        if count > 0:  # only list fields where something was actually changed
            label = CLEANING_LABELS.get(field, field)
            lines.append(f"| {label} | {count} |")
    lines.append("")

    # Flagged
    lines.append("## Flagged for review")
    lines.append("")
    if len(cleaning_summary["flagged_by_reason"]) == 0:
        lines.append("Nothing was flagged.")
    else:
        lines.append("A row can have more than one reason.")
        lines.append("")
        lines.append("| Reason | Rows |")
        lines.append("|---|---|")
        for reason, count in cleaning_summary["flagged_by_reason"].items():
            lines.append(f"| {reason} | {count} |")
    lines.append("")

    # Failures
    lines.append("## Failed records")
    lines.append("")
    if len(failure_reasons) == 0:
        lines.append("No records failed.")
    else:
        lines.append("| Reason | Rows |")
        lines.append("|---|---|")
        for reason, count in failure_reasons:
            lines.append(f"| {reason} | {count} |")
    lines.append("")

    return "\n".join(lines)


def build_details_csv(run_details, flagged_rows):
    """One line per record: row_number, customer_name, result, reason.

    Includes the rows sent to Airtable (migrated / failed) AND the flagged rows,
    so every record in the source file can be found in one place.
    """
    records = []

    for row_number, customer_name, result, reason in run_details:
        record = {
            "row_number": row_number,
            "customer_name": customer_name,
            "result": result,
            "reason": reason,
        }
        records.append(record)

    if flagged_rows is not None:
        for index, row in flagged_rows.iterrows():
            record = {
                "row_number": row["row_number"],
                "customer_name": row["customer_name"],
                "result": "flagged",
                "reason": row["issues"],
            }
            records.append(record)

    details = pd.DataFrame(records, columns=["row_number", "customer_name", "result", "reason"])
    details = details.sort_values("row_number")  # same order as the source file
    return details.to_csv(index=False)


def build_report(conn, run_id, mapping, cleaning_summary, flagged_rows):
    """Build the report for one run.

    conn:             an open connection to migration.db
    run_id:           which migration run to report on
    mapping:          the confirmed mapping, e.g. {"Cust Name": "customer_name", ...}
    cleaning_summary: the summary from cleaning.clean_and_validate()
    flagged_rows:     the flagged rows from cleaning.clean_and_validate()

    Returns (markdown_text, csv_text).
    """
    # WHY: the numbers come from the log, so the report shows what was really recorded.
    counts = count_results(conn, run_id)
    failure_reasons = get_failure_reasons(conn, run_id)
    run_details = get_run_details(conn, run_id)
    run_time = get_run_time(conn, run_id)

    markdown_text = build_markdown(run_id, run_time, mapping, cleaning_summary, counts, failure_reasons)
    csv_text = build_details_csv(run_details, flagged_rows)
    return markdown_text, csv_text


if __name__ == "__main__":
    from cleaning import clean_and_validate

    # Same hand-written mapping as in cleaning.py's and migrate.py's tests.
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

    # Clean the sample file again to get the cleaning summary and flagged rows.
    df = pd.read_csv("sample_data/messy_bookings.csv", dtype=str)
    df = df.rename(columns=COLUMN_MAPPING)
    clean_rows, flagged_rows, cleaning_summary = clean_and_validate(df)

    conn = sqlite3.connect(DB_FILE)
    latest_run_id = get_latest_run_id(conn)

    if latest_run_id is None:
        print("No migration runs found in migration_log yet. Run migrate.py first.")
    else:
        markdown_text, csv_text = build_report(conn, latest_run_id, COLUMN_MAPPING, cleaning_summary, flagged_rows)
        print(markdown_text)
        print("---------- details CSV (first 8 lines) ----------")
        csv_lines = csv_text.splitlines()
        for line in csv_lines[:8]:
            print(line)

    conn.close()
