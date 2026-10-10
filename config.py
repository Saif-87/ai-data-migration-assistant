"""Read the API keys, both locally and on Streamlit Community Cloud.

- Locally, the keys are in the .env file (never committed).
- On Streamlit Cloud there is no .env file. The keys are typed into the app's
  "Secrets" settings instead, and the code reads them from st.secrets.

Every file gets its keys through get_key(), so this is the only place that
needs to know where the keys come from.
"""

import os

import streamlit as st
from dotenv import load_dotenv


def get_key(name):
    """Return the value of a key such as "GEMINI_API_KEY", or None if it isn't set anywhere.

    The value is never printed or shown on screen.
    """
    # 1. Running locally: look in the .env file.
    load_dotenv()
    value = os.getenv(name)
    if value:
        return value

    # 2. Running on Streamlit Cloud: look in the app's Secrets.
    # WHY the try: locally there is no secrets file, and st.secrets raises an error
    # (a kind of FileNotFoundError) instead of just saying "not found".
    try:
        if name in st.secrets:
            return st.secrets[name]
    except FileNotFoundError:
        pass

    return None
