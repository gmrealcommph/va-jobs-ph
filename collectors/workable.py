import html
import re
from urllib.parse import urljoin

import requests


WORKABLE_API = "https://www.workable.com/api/accounts/{account}"
WORKABLE_BOARD_URL = "https://apply.workable.com/{account}/"

HEADERS = {
    "User-Agent": "VeeAys/1.0",
    "Accept": "application/json",
}


def fetch_workable_jobs(account):
    """Fetch currently published jobs from a public Workable account."""
    url = WORKABLE_API.format(account=account)
    response = requests.get(
        url,
        params={"details": "true"},
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()

    # Workable has returned both a {"jobs": [...]} envelope and,
    # on some public surfaces, a bare list. Support both safely.
    if isinstance(data, dict):
        jobs = data.get("jobs", [])
    elif isinstance(data, list):
        jobs = data
    else:
        jobs = []

    if not isinstance(jobs, list):
        raise ValueError(
            f"Unexpected Workable response for {account}"
        )

    return jobs


def fetch_workable_company_logo(account):
    """Best-effort company/social image discovery from the public board."""
    url = WORKABLE_BOARD_URL.format(account=account)

    try:
        response = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 VeeAys/1.0",
                "Accept": "text/html,application/xhtml+xml",
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
        match = re.search(pattern, page, flags=re.IGNORECASE)
        if not match:
            continue

        candidate = html.unescape(match.group(1).strip())
        candidate = urljoin(response.url, candidate)
        lowered = candidate.lower()

        if not candidate.startswith("https://"):
            continue
        if any(term in lowered for term in (
            "favicon", "workable-logo", "workable_logo", "powered-by-workable"
        )):
            continue
        return candidate

    return None


def _html_to_text(value):
    if not value:
        return ""

    text = html.unescape(str(value))
    text = re.sub(
        r"<\s*(br|/p|/div|/li|/h[1-6])\s*/?>",
        "\n",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def _location_to_text(raw_job):
    """Build readable location text from Workable's location fields."""
    location = raw_job.get("location")

    if isinstance(location, str):
        return location.strip()

    if isinstance(location, dict):
        parts = []
        for key in ("city", "region", "country"):
            value = location.get(key)
            if value and str(value).strip() not in parts:
                parts.append(str(value).strip())
        if parts:
            return ", ".join(parts)

    locations = raw_job.get("locations") or []
    if isinstance(locations, list):
        rendered = []
        for item in locations:
            if isinstance(item, str):
                value = item.strip()
            elif isinstance(item, dict):
                bits = [
                    str(item.get(key)).strip()
                    for key in ("city", "region", "country")
                    if item.get(key)
                ]
                value = ", ".join(dict.fromkeys(bits))
            else:
                value = ""
            if value and value not in rendered:
                rendered.append(value)
        if rendered:
            return " | ".join(rendered)

    return ""


def normalize_workable_job(
    raw_job,
    company,
    account,
    company_logo_url=None,
):
    """Convert a Workable posting into VeeAys' common job structure."""
    location = _location_to_text(raw_job)

    description_parts = []
    for heading, key in (
        (None, "description"),
        ("Requirements", "requirements"),
        ("Benefits", "benefits"),
    ):
        value = _html_to_text(raw_job.get(key))
        if not value:
            continue
        if heading:
            description_parts.append(f"{heading}\n{value}")
        else:
            description_parts.append(value)

    description = "\n\n".join(description_parts).strip()

    workplace_type = str(
        raw_job.get("workplace_type")
        or raw_job.get("workplaceType")
        or ""
    ).strip().lower().replace("-", "_")

    location_obj = raw_job.get("location")
    telecommuting = raw_job.get("telecommuting")
    if telecommuting is None and isinstance(location_obj, dict):
        telecommuting = location_obj.get("telecommuting")

    if workplace_type == "remote":
        remote = True
    elif workplace_type in {"hybrid", "on_site", "onsite"}:
        remote = False
    elif telecommuting is True:
        remote = True
        workplace_type = "remote"
    else:
        remote = None
        workplace_type = workplace_type or "unspecified"

    job_id = (
        raw_job.get("shortcode")
        or raw_job.get("id")
        or raw_job.get("code")
    )

    return {
        "title": raw_job.get("title") or "",
        "company": company,
        "company_logo_url": company_logo_url,
        "description": description,
        "category": None,
        "location": location,
        "remote": remote,
        "workplace_type": workplace_type,
        "philippines_eligible": False,
        "source": "workable",
        "source_board": account,
        "source_job_id": str(job_id) if job_id is not None else None,
        "job_url": (
            raw_job.get("url")
            or raw_job.get("shortlink")
            or raw_job.get("application_url")
        ),
        "posted_at": (
            raw_job.get("created_at")
            or raw_job.get("published_at")
        ),
        "status": "active",
        "classification_reason": None,
    }
