import html
import re
from urllib.parse import urljoin

import requests


LEVER_API_BASE = (
    "https://api.lever.co/v0/postings"
)

LEVER_JOBS_BASE = (
    "https://jobs.lever.co"
)

HEADERS = {
    "User-Agent": "VeeAys/1.0",
    "Accept": "application/json",
}


def fetch_lever_jobs(company_slug):
    """
    Fetch all currently published jobs from a company's
    public Lever job board.

    Example:
        fetch_lever_jobs("companyname")
    """

    url = (
        f"{LEVER_API_BASE}/"
        f"{company_slug}"
    )

    params = {
        "mode": "json",
    }

    response = requests.get(
        url,
        params=params,
        headers=HEADERS,
        timeout=30,
    )

    response.raise_for_status()

    jobs = response.json()

    if not isinstance(
        jobs,
        list,
    ):
        raise ValueError(
            f"Unexpected Lever response for "
            f"{company_slug}"
        )

    return jobs


def fetch_lever_company_logo(
    company_slug,
):
    """
    Try to discover the company logo or social image
    configured on the public Lever-hosted job site.

    Returns an absolute HTTPS image URL when a suitable
    image can be found.

    Returns None when no reliable image is available.
    """

    url = (
        f"{LEVER_JOBS_BASE}/"
        f"{company_slug}"
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
        (
            r'<meta[^>]+'
            r'property=["\']og:image["\']'
            r'[^>]+content=["\']([^"\']+)["\']'
        ),
        (
            r'<meta[^>]+'
            r'content=["\']([^"\']+)["\']'
            r'[^>]+property=["\']og:image["\']'
        ),
        (
            r'<meta[^>]+'
            r'name=["\']twitter:image["\']'
            r'[^>]+content=["\']([^"\']+)["\']'
        ),
        (
            r'<meta[^>]+'
            r'content=["\']([^"\']+)["\']'
            r'[^>]+name=["\']twitter:image["\']'
        ),
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

        logo_url = (
            logo_url
            .replace("\\u002F", "/")
            .replace("\\/", "/")
            .replace("&amp;", "&")
        )

        logo_url = urljoin(
            response.url,
            logo_url,
        )

        if not logo_url.startswith(
            "https://"
        ):
            continue

        logo_lower = (
            logo_url.lower()
        )

        bad_terms = [
            "favicon",
            "lever-logo",
            "lever_logo",
            "powered-by-lever",
            "powered_by_lever",
        ]

        if any(
            term in logo_lower
            for term in bad_terms
        ):
            continue

        return logo_url

    return None
