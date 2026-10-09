"""Pull booking contacts from HubSpot CRM, as a second data source next to CSV upload.

Run:  python hubspot_source.py

Uses the HubSpot REST API directly with the requests library (not the HubSpot SDK).
The values are returned exactly as they are in HubSpot. Cleaning happens later,
in cleaning.py, the same way as for a CSV.
"""

import os

import pandas as pd
import requests
from dotenv import load_dotenv

CONTACTS_URL = "https://api.hubapi.com/crm/v3/objects/contacts"

# HubSpot returns at most 100 contacts per request, so we ask for 100 at a time.
PAGE_SIZE = 100

# The HubSpot contact properties that hold the booking data (their internal names).
PROPERTIES = [
    "lastname",        # HubSpot has no "full name" field, so the import put the whole name here
    "email",
    "phone",
    "destination",
    "booked_on",
    "travel_dt",
    "price",
    "booking_status",
]


def get_token():
    """Read the HubSpot token from .env, the same way mapping.py and migrate.py read their keys.

    The token is never printed or shown on screen.
    """
    load_dotenv()
    return os.getenv("HUBSPOT_TOKEN")


def fetch_page(after):
    """Get one page of contacts (up to 100) from HubSpot and return the reply as a dict.

    after: where the previous page ended, or None for the first page.

    The reply looks like:
        {"results": [{"id": "...", "properties": {"lastname": "Janice Lee", ...}}, ...],
         "paging": {"next": {"after": "100"}}}     <- "paging" is missing on the last page
    """
    headers = {"Authorization": "Bearer " + get_token()}

    params = {
        "limit": PAGE_SIZE,
        "properties": ",".join(PROPERTIES),  # "lastname,email,phone,..."
    }
    # The first page has no cursor. Every page after that needs the cursor from the page before.
    if after is not None:
        params["after"] = after

    response = requests.get(CONTACTS_URL, headers=headers, params=params, timeout=30)

    # Turn a bad reply (e.g. 401 wrong token) into an error that fetch_contacts() can catch.
    response.raise_for_status()

    return response.json()


def fetch_contacts():
    """Fetch ALL contacts from HubSpot, page by page.

    Returns (df, error):
    - on success: a DataFrame with one column per HubSpot property, None
    - on failure: None, a friendly error message
    """
    if not get_token():
        return None, "HUBSPOT_TOKEN is not set. Add it to your .env file."

    rows = []
    after = None  # None means "start at the first page"

    # Keep asking for the next page until HubSpot says there are no more.
    while True:
        try:
            data = fetch_page(after)
        except requests.HTTPError as error:
            response = error.response        # HubSpot's reply that caused the error
            status = response.status_code    # e.g. 401
            if status == 401:
                return None, "HubSpot didn't accept the token (401). Check HUBSPOT_TOKEN in your .env file."
            if status == 403:
                return None, ("The HubSpot token doesn't have permission (403). "
                              "It needs the crm.objects.contacts.read scope.")
            return None, f"HubSpot returned an error ({status}). Please try again later."
        except requests.RequestException:
            # No internet, timeout, etc. The token is only in the headers, so it's never in this message.
            return None, "Could not reach HubSpot. Check your internet connection and try again."

        # Turn each contact into one row, keeping only our properties, values exactly as they are.
        for contact in data.get("results", []):
            properties = contact.get("properties", {})
            row = {}
            for name in PROPERTIES:
                row[name] = properties.get(name)
            rows.append(row)

        # No "next" means this was the last page.
        paging = data.get("paging")
        if paging is None:
            break
        next_page = paging.get("next")
        if next_page is None:
            break
        after = next_page.get("after")

    if len(rows) == 0:
        return None, "No contacts were found in HubSpot."

    df = pd.DataFrame(rows)
    return df, None


if __name__ == "__main__":
    df, error = fetch_contacts()

    if error is not None:
        print(f"Error: {error}")
    else:
        pd.set_option("display.width", 200)
        print("First 5 contacts:")
        print(df.head(5).to_string(index=False))
        print(f"\nTotal contacts: {len(df)}")
