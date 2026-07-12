from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def build_retrying_session() -> requests.Session:
    """A requests.Session with transport-level retry for transient errors.

    Retries 429 and 5xx for GET/POST with exponential backoff. Shared by the
    IGPSPORT and Intervals.icu clients so they follow one policy.
    """
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session = requests.Session()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session
