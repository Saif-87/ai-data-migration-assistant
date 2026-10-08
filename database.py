"""Load the messy CSV into SQLite and profile it with SQL.

Run:  python database.py

Creates migration.db with two tables:
- raw_bookings:  the messy CSV exactly as it is, original column names kept
- migration_log: empty for now; migrate.py and report.py will write to it
"""

import csv
import sqlite3
from pathlib import Path

CSV_FILE = Path("sample_data") / "messy_bookings.csv"
DB_FILE = Path("migration.db")


def quote(column):
    """Wrap a column name in double quotes so names like "Cust Name" and "Dest." work in SQL."""
    return '"' + column.replace('"', '""') + '"'


def connect(db_path=DB_FILE):
    return sqlite3.connect(db_path)


def create_migration_log(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS migration_log (
            run_id        TEXT,
            row_number    INTEGER,
            customer_name TEXT,
            result        TEXT,
            reason        TEXT,
            logged_at     TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()


def load_csv(conn, csv_path=CSV_FILE):
    """Replace raw_bookings with the contents of the CSV. Every value is stored as text, unchanged."""
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        columns = next(reader)
        rows = list(reader)

    column_list = ", ".join(quote(c) for c in columns)
    placeholders = ", ".join("?" for _ in columns)

    conn.execute("DROP TABLE IF EXISTS raw_bookings")
    conn.execute(f"CREATE TABLE raw_bookings ({', '.join(quote(c) + ' TEXT' for c in columns)})")
    conn.executemany(f"INSERT INTO raw_bookings ({column_list}) VALUES ({placeholders})", rows)
    conn.commit()
    return len(rows)


def profile(conn):
    """Run profiling queries on raw_bookings and return the results as a dictionary."""
    results = {}

    results["total_rows"] = conn.execute(
        "SELECT COUNT(*) FROM raw_bookings"
    ).fetchone()[0]

    results["missing_email"] = conn.execute("""
        SELECT COUNT(*) FROM raw_bookings
        WHERE "E-mail" IS NULL OR TRIM("E-mail") = ''
    """).fetchone()[0]

    results["missing_booked_on"] = conn.execute("""
        SELECT COUNT(*) FROM raw_bookings
        WHERE "Booked On" IS NULL OR TRIM("Booked On") = ''
    """).fetchone()[0]

    results["duplicate_emails"] = conn.execute("""
        SELECT LOWER(TRIM("E-mail")) AS email, COUNT(*) AS times
        FROM raw_bookings
        WHERE TRIM("E-mail") <> ''
        GROUP BY LOWER(TRIM("E-mail"))
        HAVING COUNT(*) > 1
        ORDER BY times DESC, email
    """).fetchall()

    results["duplicate_phones"] = conn.execute("""
        SELECT phone_no, COUNT(*) AS times
        FROM raw_bookings
        WHERE TRIM(phone_no) <> ''
        GROUP BY phone_no
        HAVING COUNT(*) > 1
        ORDER BY times DESC, phone_no
    """).fetchall()

    results["status_counts"] = conn.execute("""
        SELECT STATUS, COUNT(*) AS times
        FROM raw_bookings
        GROUP BY STATUS
        ORDER BY times DESC
    """).fetchall()

    return results


if __name__ == "__main__":
    with connect() as conn:
        loaded = load_csv(conn)
        create_migration_log(conn)
        result = profile(conn)
    conn.close()

    print(f"Loaded {loaded} rows into {DB_FILE} (table raw_bookings)\n")
    print(f"Total rows:          {result['total_rows']}")
    print(f"Missing E-mail:      {result['missing_email']}")
    print(f"Missing Booked On:   {result['missing_booked_on']}")

    print(f"\nEmails appearing more than once ({len(result['duplicate_emails'])}):")
    for email, times in result["duplicate_emails"]:
        print(f"  {email}  x{times}")

    print(f"\nPhone numbers appearing more than once ({len(result['duplicate_phones'])}):")
    for phone, times in result["duplicate_phones"]:
        print(f"  {phone}  x{times}")

    print("\nSTATUS values:")
    for status, times in result["status_counts"]:
        print(f"  {status}: {times}")
