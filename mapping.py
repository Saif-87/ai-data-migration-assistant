"""Ask Gemini to suggest how messy source columns map to the target schema.

Run:  python mapping.py

Only the column names and 3 sample rows are sent to Gemini, never the whole
file. The suggestions are checked by a person in app.py before anything is
migrated, because AI output can be wrong.
"""

import json
import os

import pandas as pd
from dotenv import load_dotenv
from google import genai
from google.genai import types

from schema import FIELDS, FIELD_NAMES

MODEL = "gemini-3.5-flash"
SAMPLE_ROWS = 3
CONFIDENCE_LEVELS = ["high", "medium", "low"]


def build_prompt(columns, sample_rows):
    """Build the text sent to Gemini: the target fields, the source columns, and a few example rows."""
    target_lines = "\n".join(
        f"- {f.name} ({f.type}, {'required' if f.required else 'optional'}): "
        f"{f.description} Format: {f.format_rule}"
        for f in FIELDS
    )

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
[
  {{"source_column": "...", "target_field": "... or null", "confidence": "high", "reason": "..."}}
]
"""


def parse_response(text, columns):
    """Turn Gemini's JSON text into a clean list of suggestions, one per source column, in source order.

    Returns (suggestions, error). Exactly one of them is empty/None.
    """
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return [], "Gemini did not return valid JSON."

    if not isinstance(data, list):
        return [], "Gemini returned JSON, but not a list of suggestions."

    by_source = {}
    for item in data:
        if isinstance(item, dict) and item.get("source_column") in columns:
            by_source[item["source_column"]] = item

    suggestions = []
    for column in columns:
        item = by_source.get(column)
        if item is None:
            suggestions.append({
                "source_column": column,
                "target_field": None,
                "confidence": "low",
                "reason": "Gemini gave no suggestion for this column.",
            })
            continue

        confidence = str(item.get("confidence", "")).lower()
        suggestions.append({
            "source_column": column,
            "target_field": item.get("target_field") or None,
            "confidence": confidence if confidence in CONFIDENCE_LEVELS else "low",
            "reason": str(item.get("reason", "")).strip(),
        })

    return suggestions, None


def suggest_mappings(df):
    """Ask Gemini to map the DataFrame's columns to the target schema.

    Returns (suggestions, error):
    - on success: (list of dicts with source_column, target_field, confidence, reason), None
    - on failure: [], a plain-English error message
    """
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return [], "GEMINI_API_KEY is not set. Add it to your .env file."

    columns = [str(c) for c in df.columns]
    sample_rows = df.head(SAMPLE_ROWS).fillna("").astype(str).to_dict(orient="records")
    prompt = build_prompt(columns, sample_rows)

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0,
            ),
        )
    except Exception as e:
        # The error type and message never contain the API key itself.
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
    sources_by_target = {}

    for s in suggestions:
        target = s["target_field"]
        if target is None:
            continue
        if target not in FIELD_NAMES:
            problems.append(f"'{s['source_column']}' maps to unknown target field '{target}'.")
            continue
        sources_by_target.setdefault(target, []).append(s["source_column"])

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
            target = s["target_field"] or "(no match)"
            print(f"{s['source_column']} → {target} ({s['confidence']}): {s['reason']}")

        problems = check_suggestions(suggestions)
        print("\nChecks: " + ("all passed" if not problems else f"{len(problems)} problem(s)"))
        for p in problems:
            print(f"  - {p}")
