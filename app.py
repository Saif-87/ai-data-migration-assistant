"""The web page that connects every step of the migration.

Run:  streamlit run app.py

How Streamlit works: every time you click something, Streamlit runs this
whole file again from top to bottom. Anything we need to remember between
clicks (like the AI's suggestions) is stored in st.session_state.
"""

import sqlite3
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from cleaning import clean_and_validate
from database import CSV_FILE, DB_FILE, create_migration_log, load_csv, profile
from hubspot_source import fetch_contacts
from mapping import MODEL, check_suggestions, suggest_mappings
from migrate import TABLE_NAME, migrate
from report import build_report
from schema import FIELD_NAMES

st.title("Data Migration Assistant")
st.write("Move messy booking data into a clean system: AI suggests the mapping, "
         "you confirm it, and Python cleans and checks the data.")


# ---------- 1. Get the data ----------
# WHAT: choose where the data comes from: a CSV file, or contacts in HubSpot CRM.
# WHY: real migrations start from different systems. After this step, both sources
# are handled exactly the same way.
st.header("1. Get the data")

source = st.radio("Where is the data?", ["Upload CSV", "Pull from HubSpot"])

if source == "Upload CSV":
    # WHAT: let the user upload a CSV, or use the sample file.
    # WHY: so the demo works straight away, even with nothing uploaded.
    uploaded_file = st.file_uploader("Upload a CSV file", type="csv")

    # Start with the sample file.
    csv_path = CSV_FILE
    file_id = str(CSV_FILE)

    if uploaded_file is not None:
        # database.load_csv() reads a file from disk, so we save the upload to a temporary file first.
        upload_path = Path(tempfile.gettempdir()) / "uploaded_bookings.csv"
        upload_path.write_bytes(uploaded_file.getvalue())
        csv_path = upload_path
        file_id = uploaded_file.name + "-" + str(uploaded_file.size)

    # Read the file. If the upload isn't a valid CSV, go back to the sample file.
    try:
        df = pd.read_csv(csv_path, dtype=str)  # dtype=str keeps every value as text, exactly as typed
    except Exception as error:
        st.write(f"**Could not read the uploaded file, so the sample file is used instead.** ({error})")
        csv_path = CSV_FILE
        file_id = str(CSV_FILE)
        df = pd.read_csv(csv_path, dtype=str)

    if csv_path == CSV_FILE:
        st.write(f"Using the sample file: {CSV_FILE}")

else:
    # WHAT: pull all contacts from HubSpot with hubspot_source.py.
    if st.button("Pull contacts again"):
        st.session_state["hubspot_df"] = None
        st.session_state["hubspot_error"] = None

    # Streamlit reruns on every click. Without this, we'd fetch from HubSpot every time.
    have_data = st.session_state.get("hubspot_df") is not None
    have_error = st.session_state.get("hubspot_error") is not None

    if not have_data and not have_error:
        hubspot_df, hubspot_error = fetch_contacts()
        st.session_state["hubspot_df"] = hubspot_df
        st.session_state["hubspot_error"] = hubspot_error

        # A new pull may bring different data, so the mapping and cleaning start fresh.
        if "hubspot_pulls" not in st.session_state:
            st.session_state["hubspot_pulls"] = 0
        st.session_state["hubspot_pulls"] = st.session_state["hubspot_pulls"] + 1

    hubspot_error = st.session_state["hubspot_error"]
    if hubspot_error is not None:
        st.write(f"**Could not pull contacts from HubSpot:** {hubspot_error}")
        st.write("Click **Pull contacts again** to retry, or choose **Upload CSV**.")
        st.stop()  # nothing to show below without data

    # Saving to a CSV makes HubSpot data look exactly like an uploaded file to every later step.
    csv_path = Path(tempfile.gettempdir()) / "hubspot_contacts.csv"
    st.session_state["hubspot_df"].to_csv(csv_path, index=False)
    file_id = "hubspot-" + str(st.session_state["hubspot_pulls"])

    df = pd.read_csv(csv_path, dtype=str)
    st.write("Pulled the contacts from HubSpot. The column names are HubSpot's property names.")

st.write(f"{len(df)} rows and {len(df.columns)} columns. Here are the first 10 rows:")
st.dataframe(df.head(10))

# WHY: if a new file was loaded, forget everything we remembered about the old file.
if st.session_state.get("file_id") != file_id:
    st.session_state["file_id"] = file_id
    st.session_state["suggestions"] = None
    st.session_state["mapping_error"] = None
    st.session_state["confirmed_mapping"] = None
    st.session_state["migration_summary"] = None
    st.session_state["report"] = None


# ---------- 2. Data profile ----------
# WHAT: load the file into SQLite and run the SQL checks from database.py.
# WHY: to see the problems in the raw data before changing anything.
st.header("2. Data profile")

result = None
profile_error = None
conn = sqlite3.connect(DB_FILE)
try:
    load_csv(conn, csv_path)
    create_migration_log(conn)
    result = profile(conn)
except sqlite3.Error as error:
    # WHY: an unusual file (e.g. two columns with the same name) can't be loaded into SQLite.
    # Show why, but let the rest of the page carry on.
    profile_error = str(error)
conn.close()

if result is None:
    st.write(f"**Could not profile this file with SQL:** {profile_error}. The rest of the page still works.")
else:
    st.metric("Total rows", result["total_rows"])
    st.metric("Fully duplicated rows", result["duplicate_rows"])

    st.write("**Missing values per column**")
    missing_table = pd.DataFrame(result["missing"], columns=["Column", "Missing"])
    st.dataframe(missing_table)

    # One small table per column that has only a few different values (like a status).
    for column, counts in result["value_counts"].items():
        st.write(f"**Values in {column}**")
        counts_table = pd.DataFrame(counts, columns=["Value", "Times"])
        st.dataframe(counts_table)


# ---------- 3. Suggested mappings ----------
# WHAT: ask Gemini which target field each column matches, and show it in a table you can edit.
# WHY: the AI does the first draft, but a person can correct it.
st.header("3. Suggested mappings")
st.write(f"Gemini ({MODEL}) sees only the column names and 3 sample rows.")
st.write("You can type a different target field in the table. Allowed names: " + ", ".join(FIELD_NAMES))
st.write("Leave the target field empty if a column has no match.")

if st.button("Ask Gemini again"):
    st.session_state["suggestions"] = None
    st.session_state["confirmed_mapping"] = None

# WHY: only call Gemini if we don't have suggestions yet.
# Without this, every click on the page would send a new request to Gemini.
if st.session_state["suggestions"] is None:
    suggestions, mapping_error = suggest_mappings(df)
    st.session_state["suggestions"] = suggestions
    st.session_state["mapping_error"] = mapping_error

suggestions = st.session_state["suggestions"]
mapping_error = st.session_state["mapping_error"]

if mapping_error is not None:
    st.write(f"**Gemini error:** {mapping_error}")
    st.write("You can still type the target fields by hand in the table below.")

    # Make one empty row per column so the person can fill them in.
    suggestions = []
    for column in df.columns:
        empty_row = {"source_column": column, "target_field": "", "confidence": "", "reason": ""}
        suggestions.append(empty_row)

suggestions_table = pd.DataFrame(suggestions)

# Only the target_field column can be edited.
edited_table = st.data_editor(suggestions_table, disabled=["source_column", "confidence", "reason"])

# Turn the edited table back into a list of suggestions.
edited_suggestions = []
for index, row in edited_table.iterrows():
    target = row["target_field"]

    # An empty cell can come back as None, NaN or "". All of them mean "no match".
    if pd.isna(target) or str(target).strip() == "":
        target = None
    else:
        target = str(target).strip()

    suggestion = {"source_column": row["source_column"], "target_field": target}
    edited_suggestions.append(suggestion)

# Build the mapping, e.g. {"Cust Name": "customer_name", ...}. Columns with no match are left out.
current_mapping = {}
for suggestion in edited_suggestions:
    if suggestion["target_field"] is not None:
        current_mapping[suggestion["source_column"]] = suggestion["target_field"]


# ---------- 4. Confirm ----------
# WHAT: check the mapping and save it when the person clicks Confirm.
# WHY: AI suggestions can be wrong, so nothing is cleaned until a person approves the mapping.
st.header("4. Confirm mapping")

if st.button("Confirm mapping"):
    problems = check_suggestions(edited_suggestions)

    if len(problems) > 0:
        # Don't save a mapping with problems. Show what's wrong instead.
        st.session_state["confirmed_mapping"] = None
        st.write("**Please fix these problems first:**")
        for problem in problems:
            st.write("- " + problem)
    else:
        st.session_state["confirmed_mapping"] = current_mapping
        st.session_state["migration_summary"] = None  # new mapping, so it can be migrated again
        st.session_state["report"] = None

confirmed_mapping = st.session_state["confirmed_mapping"]

if confirmed_mapping is None:
    st.write("Check the table above, then click **Confirm mapping**.")
else:
    st.write(f"**Mapping confirmed:** {len(confirmed_mapping)} of {len(df.columns)} columns mapped.")

    # WHY: if the table was edited after confirming, the results below use the OLD mapping.
    if current_mapping != confirmed_mapping:
        st.write("**Note:** you changed the table after confirming. "
                 "Click **Confirm mapping** again to use your changes.")


# ---------- 5. Cleaning results ----------
# WHAT: rename the columns, then clean and check every row with cleaning.py.
# WHY: show what was fixed automatically and which rows need a person to look at them.
st.header("5. Cleaning results")

clean_rows = None  # stays None until cleaning has run; section 6 checks this

if confirmed_mapping is None:
    st.write("Confirm the mapping to see the cleaning results.")
else:
    # Rename the columns to the target names, e.g. "Cust Name" becomes "customer_name".
    renamed_df = df.rename(columns=confirmed_mapping)

    clean_rows, flagged_rows, summary = clean_and_validate(renamed_df)

    st.metric("Total rows", summary["total_rows"])
    st.metric("Clean rows", summary["clean_rows"])
    st.metric("Flagged for review", summary["flagged_rows"])

    # Turn the "values cleaned" counts into a small table.
    st.write("**Values fixed automatically, per field**")
    cleaned_counts = []
    for field, count in summary["values_cleaned"].items():
        cleaned_counts.append({"Field": field, "Values changed": count})
    st.dataframe(pd.DataFrame(cleaned_counts))

    # Turn the "flagged by reason" counts into a small table.
    st.write("**Problems found** (a row can have more than one)")
    reason_counts = []
    for reason, count in summary["flagged_by_reason"].items():
        reason_counts.append({"Reason": reason, "Rows": count})
    st.dataframe(pd.DataFrame(reason_counts))

    st.write(f"**Clean rows ({len(clean_rows)})**")
    st.dataframe(clean_rows)

    # WHY: flagged rows are never dropped; they're shown here so a person can review them.
    st.write(f"**Flagged rows ({len(flagged_rows)})**: not dropped, kept here for review.")
    st.dataframe(flagged_rows)


# ---------- 6. Migrate and report ----------
# WHAT: send the clean rows to Airtable with migrate.py, then show what happened.
# WHY: only clean rows are sent. Flagged rows stay here until a person fixes them.
st.header("6. Migrate and report")

if clean_rows is None:
    # Cleaning hasn't run yet, so there is nothing to send.
    st.button("Migrate to Airtable", disabled=True)
    st.write("Confirm the mapping first. Then you can migrate the clean rows.")

elif st.session_state["migration_summary"] is not None:
    # WHY: switch the button off after a migration, so clicking twice doesn't
    # create the same bookings twice in Airtable.
    st.button("Migrate to Airtable", disabled=True)
    st.write("These rows have already been migrated. Load a new file or confirm a new mapping to migrate again.")

else:
    st.write(f"This will send {len(clean_rows)} clean rows to the Airtable table '{TABLE_NAME}'. "
             f"The {len(flagged_rows)} flagged rows are not sent.")

    if st.button("Migrate to Airtable"):
        progress_bar = st.progress(0)

        # migrate() calls this after each batch of 10 rows, so the bar moves while sending.
        def show_progress(rows_done, total_rows):
            progress_bar.progress(rows_done / total_rows, text=f"Sent {rows_done} of {total_rows} rows")

        st.session_state["migration_summary"] = migrate(clean_rows, show_progress)

        # Run the page again so the button switches off straight away.
        st.rerun()

# Show the result of the last migration.
migration_summary = st.session_state["migration_summary"]

if migration_summary is not None:
    if migration_summary["error"] is not None:
        st.write(f"**Migration could not start:** {migration_summary['error']}")
    else:
        st.write(f"**Migration finished.** Run id: {migration_summary['run_id']}")
        st.metric("Migrated to Airtable", migration_summary["migrated"])
        st.metric("Failed", migration_summary["failed"])

        if migration_summary["failed"] > 0:
            st.write("**Rows that failed** (also saved in the migration_log table):")
            st.dataframe(pd.DataFrame(migration_summary["failed_rows"]))


# ---------- 7. Report ----------
# WHAT: build the migration report with report.py and offer it as two downloads.
# WHY: a migration needs a record of what was mapped, cleaned, flagged, sent and failed.
st.header("7. Report")

migration_worked = migration_summary is not None and migration_summary["error"] is None

if not migration_worked:
    # No migration yet, so there is nothing to report on.
    st.button("Show report", disabled=True)
    st.write("Migrate the clean rows first. Then you can see the report.")
else:
    if st.button("Show report"):
        # The migrated / failed numbers are read from the migration_log table for this run.
        conn = sqlite3.connect(DB_FILE)
        markdown_text, csv_text = build_report(
            conn, migration_summary["run_id"], confirmed_mapping, summary, flagged_rows
        )
        conn.close()
        st.session_state["report"] = {"markdown": markdown_text, "csv": csv_text}

# WHY: the report is kept in session_state, so it stays on the page after clicking a download button.
report = st.session_state["report"]

if report is not None:
    st.markdown(report["markdown"])

    st.download_button(
        "Download report (.md)",
        data=report["markdown"],
        file_name=f"migration_report_{migration_summary['run_id']}.md",
        mime="text/markdown",
    )
    st.download_button(
        "Download details (.csv)",
        data=report["csv"],
        file_name=f"migration_details_{migration_summary['run_id']}.csv",
        mime="text/csv",
    )
