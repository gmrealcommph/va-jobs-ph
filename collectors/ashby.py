import html
import re

import requests


ASHBY_API_BASE = "https://api.ashbyhq.com/posting-api/job-board"
ASHBY_JOB_BOARD_BASE = "https://jobs.ashbyhq.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json",
}


def fetch_ashby_jobs(company_slug):
    url = f"{ASHBY_API_BASE}/{company_slug}"

    params = {
        "includeCompensation": "true",
    }

    headers = {
        "User-Agent": "VAJobsPH/1.0",
        "Accept": "application/json",
    }

    response = requests.get(
        url,
        params=params,
        headers=headers,
        timeout=30,
    )

    response.raise_for_status()

    data = response.json()

    jobs = data.get("jobs", [])

    if not isinstance(jobs, list):
        raise ValueError(
            f"Unexpected Ashby response for {company_slug}"
        )

    # Ashby can expose unlisted jobs through some API surfaces.
    # Only retain jobs intended to appear publicly.
    jobs = [
        job
        for job in jobs
        if job.get("isListed", True)
    ]

    return jobs


def fetch_ashby_company_logo(company_slug):
    """
    Try to obtain the company branding image configured on the
    public Ashby job board.

    Returns:
        Absolute image URL when a suitable logo is found.
        None when no reliable logo can be identified.

    Logo discovery failure must never interrupt job collection.
    """

    board_url = f"{ASHBY_JOB_BOARD_BASE}/{company_slug}"

    try:
        response = requests.get(
            board_url,
            headers=HEADERS,
            timeout=20,
        )

        response.raise_for_status()

        page = response.text

        # -----------------------------------------------------
        # 1. OPEN GRAPH IMAGE
        # -----------------------------------------------------
        #
        # Ashby pages may expose their configured branding
        # through social metadata. Prefer this because it is
        # explicitly associated with the public board page.

        og_patterns = [
            (
                r'<meta[^>]+property=["\']og:image["\']'
                r'[^>]+content=["\']([^"\']+)["\']'
            ),
            (
                r'<meta[^>]+content=["\']([^"\']+)["\']'
                r'[^>]+property=["\']og:image["\']'
            ),
        ]

        for pattern in og_patterns:
            match = re.search(
                pattern,
                page,
                flags=re.IGNORECASE,
            )

            if match:
                candidate = _clean_logo_url(
                    match.group(1)
                )

                if _is_usable_logo_url(candidate):
                    return candidate

        # -----------------------------------------------------
        # 2. TWITTER IMAGE
        # -----------------------------------------------------

        twitter_patterns = [
            (
                r'<meta[^>]+name=["\']twitter:image["\']'
                r'[^>]+content=["\']([^"\']+)["\']'
            ),
            (
                r'<meta[^>]+content=["\']([^"\']+)["\']'
                r'[^>]+name=["\']twitter:image["\']'
            ),
        ]

        for pattern in twitter_patterns:
            match = re.search(
                pattern,
                page,
                flags=re.IGNORECASE,
            )

            if match:
                candidate = _clean_logo_url(
                    match.group(1)
                )

                if _is_usable_logo_url(candidate):
                    return candidate

        # -----------------------------------------------------
        # 3. ASHBY BRANDING IMAGE REFERENCES
        # -----------------------------------------------------
        #
        # Some boards expose the configured organization logo
        # inside serialized page data rather than meta tags.

        logo_patterns = [
            r'"logoUrl"\s*:\s*"([^"]+)"',
            r'"logoURL"\s*:\s*"([^"]+)"',
            r'"logo"\s*:\s*"([^"]+\.(?:png|jpg|jpeg|webp|svg)[^"]*)"',
        ]

        for pattern in logo_patterns:
            matches = re.findall(
                pattern,
                page,
                flags=re.IGNORECASE,
            )

            for raw_candidate in matches:
                candidate = _clean_logo_url(
                    raw_candidate
                )

                if _is_usable_logo_url(candidate):
                    return candidate

    except Exception as error:
        print(
            f"  LOGO LOOKUP SKIPPED: "
            f"{company_slug} - {error}"
        )

    return None


def _clean_logo_url(value):
    if not value:
        return None

    value = html.unescape(value.strip())

    # Serialized JSON sometimes escapes forward slashes.
    value = value.replace("\\/", "/")

    # Handle common JSON unicode escaping.
    value = value.replace("\\u0026", "&")
    value = value.replace("\\u003d", "=")

    if value.startswith("//"):
        value = f"https:{value}"

    return value


def _is_usable_logo_url(url):
    """
    Apply conservative checks so VeeAys doesn't accidentally
    save an unrelated image as a company's logo.
    """

    if not url:
        return False

    if not url.startswith(("https://", "http://")):
        return False

    lowered = url.lower()

    rejected_terms = [
        "favicon",
        "apple-touch-icon",
        "ashby-logo",
        "ashby_logo",
        "powered-by-ashby",
        "poweredbyashby",
    ]

    if any(
        term in lowered
        for term in rejected_terms
    ):
        return False

    return True
