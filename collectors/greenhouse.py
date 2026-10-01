import html
import re
from urllib.parse import urljoin

import requests


GREENHOUSE_API = (
    "https://boards-api.greenhouse.io/"
    "v1/boards/{board}/jobs"
)

GREENHOUSE_BOARD_URL = (
    "https://boards.greenhouse.io/{board}"
)

HEADERS = {
    "User-Agent": "VeeAys/1.0",
    "Accept": "application/json",
}


def fetch_greenhouse_jobs(board):
    """
    Fetch all currently published jobs from a Greenhouse job board.
    """

    url = GREENHOUSE_API.format(
        board=board
    )

    response = requests.get(
        url,
        params={
            "content": "true",
        },
        headers=HEADERS,
        timeout=30,
    )

    response.raise_for_status()

    data = response.json()

    jobs = data.get(
        "jobs",
        [],
    )

    if not isinstance(
        jobs,
        list,
    ):
        raise ValueError(
            f"Unexpected Greenhouse response for {board}"
        )

    return jobs


def fetch_greenhouse_logo(board):
    """
    Try to discover the company logo configured on the
    public Greenhouse job board.

    Returns an absolute HTTPS image URL when available.
    Otherwise returns None.
    """

    url = GREENHOUSE_BOARD_URL.format(
        board=board
    )

    try:
        response = requests.get(
            url,
            headers={
                "User-Agent":
                    "Mozilla/5.0 VeeAys/1.0",
                "Accept":
                    "text/html,application/xhtml+xml",
            },
            timeout=30,
            allow_redirects=True,
        )

        response.raise_for_status()

    except requests.RequestException:
        return None

    page = response.text

    patterns = [
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
        r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']',
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            page,
            flags=re.IGNORECASE,
        )

        if not match:
            continue

        logo_url = html.unescape(
            match.group(1).strip()
        )

        logo_url = urljoin(
            response.url,
            logo_url,
        )

        if logo_url.startswith(
            "https://"
        ):
            return logo_url

    return None


def clean_greenhouse_description(content):
    """
    Convert Greenhouse's HTML-escaped job description
    into clean plain text for storage and searching.
    """

    if not content:
        return ""

    text = html.unescape(
        content
    )

    text = re.sub(
        r"<\s*(br|/p|/div|/li|/h[1-6])\s*/?>",
        "\n",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"<[^>]+>",
        " ",
        text,
    )

    text = html.unescape(
        text
    )

    text = re.sub(
        r"[ \t]+",
        " ",
        text,
    )

    text = re.sub(
        r"\n\s*\n+",
        "\n\n",
        text,
    )

    return text.strip()


def normalize_greenhouse_job(
    job,
    company,
    board,
    company_logo_url=None,
):
    """
    Convert a Greenhouse job into our standard database format.
    """

    location = (
        job.get(
            "location",
            {},
        ).get(
            "name",
            "",
        )
        or ""
    )

    description = (
        clean_greenhouse_description(
            job.get(
                "content",
                "",
            )
        )
    )

    location_lower = (
        location.lower()
    )

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
        "title":
            job.get("title")
            or "",

        "company":
            company,

        "company_logo_url":
            company_logo_url,

        "description":
            description,

        "category":
            None,

        "location":
            location,

        "remote":
            remote,

        "workplace_type":
            (
                "remote"
                if remote
                else "unspecified"
            ),

        "philippines_eligible":
            False,

        "source":
            "greenhouse",

        "source_board":
            board,

        "source_job_id":
            (
                str(job.get("id"))
                if job.get("id")
                is not None
                else None
            ),

        "job_url":
            job.get(
                "absolute_url"
            ),

        "posted_at":
            job.get(
                "updated_at"
            ),

        "status":
            "active",

        "classification_reason":
            None,
    }
