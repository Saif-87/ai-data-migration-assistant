"""Load the messy CSV into a SQLite database and look at it with SQL.

Run:  python database.py

This creates a file called migration.db with two tables:
- raw_bookings:  the messy CSV exactly as it is, with the original column names
- migration_log: empty for now; migrate.py and report.py will write to it later
"""

import csv
import sqlite3
from pathlib import Path

CSV_FILE = Path("sample_data") / "messy_bookings.csv"
DB_FILE = Path("migration.db")


def quote(column):
    """Wrap a column name in double quotes so SQL accepts it.

    Column names like "Cust Name" (space) or "Dest." (dot) confuse SQL, so we wrap
    them in double quotes. A " inside the name is written twice ("") so it doesn't
    end the name early.
    """
    return '"' + column.replace('"', '""') + '"'


def create_migration_log(conn):
    # Unlike raw_bookings, the log is never deleted, so the history of past migrations is kept.
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
    """Replace raw_bookings with the contents of the CSV. Returns how many rows were loaded."""
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        columns = next(reader)  # the first line is the header
        rows = list(reader)     # every other line is a row

    quoted_columns = []      # ['"Cust Name"', '"E-mail"', ...]
    column_definitions = []  # ['"Cust Name" TEXT', '"E-mail" TEXT', ...]
    placeholders = []        # ['?', '?', ...] one per column
    for column in columns:
        quoted_columns.append(quote(column))
        column_definitions.append(quote(column) + " TEXT")
        placeholders.append("?")

    # Every column is TEXT and values are stored exactly as in the CSV.
    # This table is the "before" picture; cleaning happens later, in cleaning.py.
    create_sql = "CREATE TABLE raw_bookings (" + ", ".join(column_definitions) + ")"

    # The ? marks are filled in by sqlite3. It's safer than pasting values into the SQL text,
    # because a value like O'Brien won't break the query.
    insert_sql = ("INSERT INTO raw_bookings (" + ", ".join(quoted_columns) + ") "
                  "VALUES (" + ", ".join(placeholders) + ")")

    # Start fresh each time, so loading twice doesn't give 200 rows.
    conn.execute("DROP TABLE IF EXISTS raw_bookings")
    conn.execute(create_sql)
    conn.executemany(insert_sql, rows)  # insert all rows in one go
    conn.commit()
    return len(rows)


def profile(conn):
    """Run SQL checks on raw_bookings and return the results as a dictionary."""
    results = {}

    # How many rows in total
    row = conn.execute("SELECT COUNT(*) FROM raw_bookings").fetchone()  # one row, e.g. (100,)
    results["total_rows"] = row[0]                                       # take the number out

    # A cell counts as missing if it's empty or only spaces (TRIM removes spaces at both ends).
    row = conn.execute("""
        SELECT COUNT(*) FROM raw_bookings
        WHERE "E-mail" IS NULL OR TRIM("E-mail") = ''
    """).fetchone()
    results["missing_email"] = row[0]

    row = conn.execute("""
        SELECT COUNT(*) FROM raw_bookings
        WHERE "Booked On" IS NULL OR TRIM("Booked On") = ''
    """).fetchone()
    results["missing_booked_on"] = row[0]

    # Emails used more than once.
    # Blank emails are skipped, otherwise all the blanks would look like one big duplicate.
    # LOWER makes "A@x.com" and "a@x.com" count as the same email.
    # HAVING is like WHERE, but it filters groups instead of single rows.
    results["duplicate_emails"] = conn.execute("""
        SELECT LOWER(TRIM("E-mail")) AS email, COUNT(*) AS times
        FROM raw_bookings
        WHERE TRIM("E-mail") <> ''
        GROUP BY LOWER(TRIM("E-mail"))
        HAVING COUNT(*) > 1
        ORDER BY times DESC, email
    """).fetchall()

    # Phone numbers used more than once.
    # Only finds numbers typed exactly the same. "+971 50..." and "050..." won't match
    # until cleaning.py puts every number in one format.
    results["duplicate_phones"] = conn.execute("""
        SELECT phone_no, COUNT(*) AS times
        FROM raw_bookings
        WHERE TRIM(phone_no) <> ''
        GROUP BY phone_no
        HAVING COUNT(*) > 1
        ORDER BY times DESC, phone_no
    """).fetchall()

    # Each STATUS value and how many times it appears, most common first.
    results["status_counts"] = conn.execute("""
        SELECT STATUS, COUNT(*) AS times
        FROM raw_bookings
        GROUP BY STATUS
        ORDER BY times DESC
    """).fetchall()

    return results


if __name__ == "__main__":
    conn = sqlite3.connect(DB_FILE)
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
