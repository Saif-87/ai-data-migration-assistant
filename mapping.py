"""Ask Gemini (Google's AI) to suggest how messy source columns match the target fields.

Run:  python mapping.py

Only the column names and 3 sample rows are sent to Gemini, never the whole
file. A person checks the suggestions in app.py before anything is migrated,
because AI answers can be wrong.
"""

import json
import os

import pandas as pd
from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

from schema import FIELDS, FIELD_NAMES

# gemini-3.8-flash is newer, but on the free tier it often replied "503 busy" (Oct 2026).
# 3.5 Flash answered reliably. Change this one line to try another model.
MODEL = "gemini-3.5-flash"

# Only a few rows are sent: enough for the AI to see what the values look like,
# without sending customer data it doesn't need.
SAMPLE_ROWS = 3

CONFIDENCE_LEVELS = ["high", "medium", "low"]

# Showing the AI the exact shape we want back makes it much more likely to follow it.
# This is a normal string (not an f-string), so the { } can be written as they are.
JSON_EXAMPLE = """[
  {"source_column": "...", "target_field": "... or null", "confidence": "high", "reason": "..."}
]"""


def build_prompt(columns, sample_rows):
    """Build the text sent to Gemini: the target fields, the source columns, and a few example rows."""
    lines = []
    for field in FIELDS:
        if field.required:
            required_text = "required"
        else:
            required_text = "optional"
        lines.append(f"- {field.name} ({field.type}, {required_text}): "
                     f"{field.description} Format: {field.format_rule}")
    target_lines = "\n".join(lines)

    return f"""You are helping migrate travel booking records from a messy spreadsheet into a clean system.

Target fields:
{target_lines}

Source columns:
{json.dumps(columns)}

Sample source rows (values may be messy, missing or in mixed formats):
{json.dumps(sample_rows, indent=2)}

For EACH source column, suggest which target field it maps to.
Rules:
- Use only the exact target field names listed above, or null if the column fits no target field.
- Map each target field to at most one source column.
- Judge by both the column name and the sample values.
- confidence must be "high", "medium" or "low".
- reason must be one short sentence.

Reply with JSON only, in exactly this shape:
{JSON_EXAMPLE}
"""


def parse_response(text, columns):
    """Turn Gemini's JSON reply into a clean list of suggestions.

    Never trust the AI's reply as-is. We rebuild it so there is exactly one suggestion
    per source column, in the original order, even if the AI skipped or invented columns.

    Returns (suggestions, error). On success error is None; on failure suggestions is [].
    """
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return [], "Gemini did not return valid JSON."

    if not isinstance(data, list):
        return [], "Gemini returned JSON, but not a list of suggestions."

    # Look up each suggestion by its source column name.
    by_source = {}
    for item in data:
        if not isinstance(item, dict):
            continue  # skip anything that isn't a {...} object
        source = item.get("source_column")
        if source in columns:
            by_source[source] = item

    suggestions = []
    for column in columns:
        item = by_source.get(column)

        # The AI skipped this column: add it anyway, with no match.
        if item is None:
            suggestions.append({
                "source_column": column,
                "target_field": None,
                "confidence": "low",
                "reason": "Gemini gave no suggestion for this column.",
            })
            continue

        target = item.get("target_field")
        if not target:
            target = None  # treat an empty answer ("") as "no match"

        # If the AI gives a confidence we don't recognise, assume low so a person checks it.
        confidence = str(item.get("confidence", "")).lower()
        if confidence not in CONFIDENCE_LEVELS:
            confidence = "low"

        reason = str(item.get("reason", "")).strip()

        suggestions.append({
            "source_column": column,
            "target_field": target,
            "confidence": confidence,
            "reason": reason,
        })

    return suggestions, None


def suggest_mappings(df):
    """Ask Gemini to match the DataFrame's columns to the target fields.

    Returns (suggestions, error):
    - on success: (list of dicts with source_column, target_field, confidence, reason), None
    - on failure: [], a plain-English error message
    """
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return [], "GEMINI_API_KEY is not set. Add it to your .env file."

    columns = list(df.columns)

    sample = df.head(SAMPLE_ROWS)                     # first 3 rows only
    sample = sample.fillna("")                        # empty cells are NaN, which can't go into JSON; "" can
    sample = sample.astype(str)                       # everything as text
    sample_rows = sample.to_dict(orient="records")    # [{"Cust Name": "...", ...}, ...]

    prompt = build_prompt(columns, sample_rows)

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",  # JSON only, no chatty text around it
                temperature=0,  # as consistent as possible, so the same file gets the same mapping
            ),
        )
    except errors.ClientError as e:
        # 429 = too many requests. On the free tier this means the daily limit is used up.
        if e.code == 429:
            return [], "Gemini's free daily limit is used up. Type the mappings by hand, or try again later."
        return [], f"Gemini request failed ({type(e).__name__}): {e}"
    except errors.ServerError as e:
        # 503 = Gemini is overloaded. It usually clears up after a minute or two.
        if e.code == 503:
            return [], "Gemini is busy right now. Click Ask Gemini again in a minute, or type the mappings by hand."
        return [], f"Gemini request failed ({type(e).__name__}): {e}"
    except Exception as e:
        # Any other failure (no internet, busy server, wrong key) becomes a message for the user
        # instead of crashing the app. The message never includes the API key.
        return [], f"Gemini request failed ({type(e).__name__}): {e}"

    return parse_response(response.text, columns)


def check_suggestions(suggestions):
    """Check Gemini's suggestions before they are shown or used.

    Rules:
    1. Every target_field must be a real field name from schema.py (see FIELD_NAMES), or None.
    2. No target field may be used by more than one source column.

    Returns a list of problem messages (strings), one per problem found, e.g.
        ["'Price' maps to unknown target field 'price_aed'.",
         "Target field 'email' is used by more than one column: E-mail, Contact."]
    Returns an empty list [] if everything is fine.
    """
    problems = []
    sources_by_target = {}  # e.g. {"email": ["E-mail", "Contact"]}

    for s in suggestions:
        target = s["target_field"]
        if target is None:
            continue  # "no match" is allowed for any number of columns
        if target not in FIELD_NAMES:
            problems.append(f"'{s['source_column']}' maps to unknown target field '{target}'.")
            continue
        if target not in sources_by_target:
            sources_by_target[target] = []
        sources_by_target[target].append(s["source_column"])

    for target, sources in sources_by_target.items():
        if len(sources) > 1:
            problems.append(
                f"Target field '{target}' is used by more than one column: {', '.join(sources)}."
            )

    return problems


if __name__ == "__main__":
    df = pd.read_csv("sample_data/messy_bookings.csv", dtype=str)
    suggestions, error = suggest_mappings(df)

    if error:
        print(f"Error: {error}")
    else:
        print(f"Model: {MODEL}\n")
        for s in suggestions:
            target = s["target_field"]
            if target is None:
                target = "(no match)"
            print(f"{s['source_column']} → {target} ({s['confidence']}): {s['reason']}")

        problems = check_suggestions(suggestions)
        if problems:
            print(f"\nChecks: {len(problems)} problem(s)")
        else:
            print("\nChecks: all passed")
        for p in problems:
            print(f"  - {p}")
