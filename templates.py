"""Save and reuse confirmed mappings ("templates").

A template is a small JSON file in the templates/ folder, for example templates/hubspot_bookings.json:

    {
      "name": "hubspot_bookings",
      "source_columns": ["lastname", "email", ...],
      "mapping": {"lastname": "customer_name", "email": "email", ...}
    }

When new data arrives with exactly the same column names as a template, the app loads
the template's mapping instead of asking Gemini.
"""

import json
from pathlib import Path

TEMPLATES_DIR = Path("templates")


def clean_template_name(name):
    """Turn what the user typed into a safe file name: "HubSpot bookings" -> "hubspot_bookings".

    Only letters, digits, "_" and "-" are kept. Returns "" if nothing is left.
    """
    name = name.strip().lower().replace(" ", "_")
    safe_name = ""
    for character in name:
        if character.isalnum() or character == "_" or character == "-":
            safe_name = safe_name + character
    return safe_name


def save_template(name, source_columns, mapping):
    """Save a confirmed mapping as templates/<name>.json.

    name:           what the user typed, e.g. "hubspot_bookings"
    source_columns: every column name in the data, e.g. ["lastname", "email", ...]
    mapping:        the confirmed mapping, e.g. {"lastname": "customer_name", ...}

    Returns (path, error). On success error is None; on failure path is None.
    A template with the same name is replaced.
    """
    safe_name = clean_template_name(name)
    if safe_name == "":
        return None, "Please type a name for the template (letters, numbers, _ or -)."

    template = {
        "name": safe_name,
        "source_columns": list(source_columns),
        "mapping": mapping,
    }

    TEMPLATES_DIR.mkdir(exist_ok=True)  # create the templates folder if it doesn't exist
    path = TEMPLATES_DIR / (safe_name + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(template, f, indent=2)

    return path, None


def find_template(columns):
    """Return the saved template whose column names match these columns, or None.

    WHY match on the set of names: the same data can come with its columns in a different
    order, but if the names are the same, the same mapping applies.
    """
    if not TEMPLATES_DIR.exists():
        return None

    wanted = set(columns)

    for path in sorted(TEMPLATES_DIR.glob("*.json")):
        try:
            with open(path, encoding="utf-8") as f:
                template = json.load(f)
        except (OSError, ValueError):
            continue  # skip a file that can't be read or isn't valid JSON

        if not isinstance(template, dict):
            continue
        if set(template.get("source_columns", [])) == wanted:
            return template

    return None


def template_to_suggestions(template, columns):
    """Turn a template into the same kind of suggestion list Gemini gives, one per column.

    This way the table in app.py doesn't need to know where the mapping came from.
    """
    mapping = template.get("mapping", {})
    suggestions = []
    for column in columns:
        target = mapping.get(column)  # None if the template left this column unmapped
        suggestion = {
            "source_column": column,
            "target_field": target,
            "confidence": "template",
            "reason": "From template " + template.get("name", "") + ".",
        }
        suggestions.append(suggestion)
    return suggestions
