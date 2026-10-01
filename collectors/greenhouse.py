import html
import re

import requests


GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs"


def fetch_greenhouse_jobs(board):
    """
    Fetch all currently published jobs from a Greenhouse job board.
    """

    url = GREENHOUSE_API.format(board=board)

    response = requests.get(
        url,
        params={"content": "true"},
        timeout=30,
    )

    response.raise_for_status()

    data = response.json()

    return data.get("jobs", [])


def clean_greenhouse_description(content):
    """
    Convert Greenhouse's HTML-escaped job description
    into clean plain text for storage and searching.
    """

    if not content:
        return ""

    # Greenhouse content can be HTML-escaped.
    text = html.unescape(content)

    # Add spacing where common block elements occur.
    text = re.sub(
        r"<\s*(br|/p|/div|/li|/h[1-6])\s*/?>",
        "\n",
        text,
        flags=re.IGNORECASE,
    )

    # Remove remaining HTML tags.
    text = re.sub(r"<[^>]+>", " ", text)

    # Decode any entities that remained after tag removal.
    text = html.unescape(text)

    # Clean whitespace while preserving useful paragraph breaks.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)

    return text.strip()


def normalize_greenhouse_job(job, company, board):
    """
    Convert a Greenhouse job into our standard database format.
    """

    location = (
        job.get("location", {}).get("name", "")
        or ""
    )

    description = clean_greenhouse_description(
        job.get("content", "")
    )

    location_lower = location.lower()

    remote_location_terms = [
        "remote",
        "work from home",
        "work-from-home",
        "wfh",
        "home based",
        "home-based",
        "worldwide",
        "anywhere",
        "global",
    ]

    remote = any(
        term in location_lower
        for term in remote_location_terms
    )

    return {
        "title": job.get("title") or "",
        "company": company,
        "description": description,
        "category": None,
        "location": location,
        "remote": remote,
        "workplace_type": (
            "remote"
            if remote
            else "unspecified"
        ),
        "philippines_eligible": False,
        "source": "greenhouse",
        "source_board": board,
        "source_job_id": (
            str(job.get("id"))
            if job.get("id") is not None
            else None
        ),
        "job_url": job.get("absolute_url"),
        "posted_at": job.get("updated_at"),
        "status": "active",
        "classification_reason": None,
    }
