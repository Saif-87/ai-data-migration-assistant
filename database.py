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

# A column with this many different values or fewer gets a count per value (e.g. a status column).
MAX_DIFFERENT_VALUES = 10


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


def get_columns(conn):
    """Return the column names of raw_bookings, read from the table itself.

    WHY: the profile must work with any file (a CSV, HubSpot contacts ...),
    so we never type column names by hand.
    """
    # PRAGMA table_info gives one row per column: (position, name, type, ...)
    columns = []
    for column_info in conn.execute("PRAGMA table_info(raw_bookings)").fetchall():
        columns.append(column_info[1])
    return columns


def profile(conn):
    """Run SQL checks on raw_bookings and return the results as a dictionary.

    Works with any columns:
    - total_rows:     how many rows there are
    - missing:        [(column, how many empty cells), ...] for every column
    - duplicate_rows: how many rows are exact copies of an earlier row
    - value_counts:   {column: [(value, times), ...]} for columns with only a few different values
    """
    results = {}
    columns = get_columns(conn)

    # How many rows in total
    row = conn.execute("SELECT COUNT(*) FROM raw_bookings").fetchone()  # one row, e.g. (100,)
    results["total_rows"] = row[0]                                       # take the number out

    # Missing values in each column.
    # A cell counts as missing if it's empty or only spaces (TRIM removes spaces at both ends).
    results["missing"] = []
    for column in columns:
        sql = f"SELECT COUNT(*) FROM raw_bookings WHERE {quote(column)} IS NULL OR TRIM({quote(column)}) = ''"
        row = conn.execute(sql).fetchone()
        results["missing"].append((column, row[0]))

    # Rows that are exact copies: the same value in EVERY column.
    # GROUP BY all columns puts identical rows together; each group of 3 means 2 extra copies.
    quoted_columns = []
    for column in columns:
        quoted_columns.append(quote(column))
    all_columns = ", ".join(quoted_columns)
    row = conn.execute(f"""
        SELECT SUM(times - 1) FROM (
            SELECT COUNT(*) AS times
            FROM raw_bookings
            GROUP BY {all_columns}
            HAVING COUNT(*) > 1
        )
    """).fetchone()
    if row[0] is None:
        results["duplicate_rows"] = 0  # SUM of nothing is NULL, which means no copies
    else:
        results["duplicate_rows"] = row[0]

    # How often each value appears, but only for columns with a few different values (like a status).
    # WHY: for names or emails almost every value is different, so a count per value isn't useful.
    results["value_counts"] = {}
    for column in columns:
        q = quote(column)
        row = conn.execute(
            f"SELECT COUNT(DISTINCT {q}) FROM raw_bookings WHERE TRIM({q}) <> ''"
        ).fetchone()
        different_values = row[0]

        if different_values > 0 and different_values <= MAX_DIFFERENT_VALUES:
            counts = conn.execute(f"""
                SELECT {q}, COUNT(*) AS times
                FROM raw_bookings
                WHERE TRIM({q}) <> ''
                GROUP BY {q}
                ORDER BY times DESC
            """).fetchall()
            results["value_counts"][column] = counts

    return results


if __name__ == "__main__":
    conn = sqlite3.connect(DB_FILE)
    loaded = load_csv(conn)
    create_migration_log(conn)
    result = profile(conn)
    conn.close()

    print(f"Loaded {loaded} rows into {DB_FILE} (table raw_bookings)\n")
    print(f"Total rows:            {result['total_rows']}")
    print(f"Fully duplicated rows: {result['duplicate_rows']}")

    print("\nMissing values per column:")
    for column, missing in result["missing"]:
        print(f"  {column:<16} {missing}")

    print("\nValue counts (columns with few different values):")
    for column, counts in result["value_counts"].items():
        print(f"  {column}:")
        for value, times in counts:
            print(f"    {value}: {times}")
