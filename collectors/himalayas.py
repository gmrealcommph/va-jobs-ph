import html
import re
from datetime import datetime, timezone

import requests


HIMALAYAS_SEARCH_API = "https://himalayas.app/jobs/api/search"
HIMALAYAS_SOURCE_URL = "https://himalayas.app"

HEADERS = {
    "User-Agent": "VeeAys/1.0",
    "Accept": "application/json",
}


def fetch_himalayas_jobs(country="PH", timeout=30, max_pages=200):
    """
    Fetch remote jobs eligible for a country from Himalayas' public API.

    Himalayas' country search includes worldwide-friendly jobs unless
    exclude_worldwide=true is supplied. We intentionally leave that flag
    unset so a PH search returns both Philippines-restricted and worldwide
    remote jobs that a Philippines-based applicant can apply for.
    """
    all_jobs = []
    seen_ids = set()
    page = 1

    while page <= max_pages:
        response = requests.get(
            HIMALAYAS_SEARCH_API,
            params={
                "country": country,
                "sort": "recent",
                "page": page,
            },
            headers=HEADERS,
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()

        if not isinstance(data, dict):
            raise ValueError("Unexpected Himalayas API response")

        jobs = data.get("jobs") or []
        if not isinstance(jobs, list):
            raise ValueError("Unexpected Himalayas jobs payload")

        for job in jobs:
            if not isinstance(job, dict):
                continue

            job_id = job.get("guid")
            dedupe_key = str(job_id) if job_id else None

            if dedupe_key and dedupe_key in seen_ids:
                continue

            if dedupe_key:
                seen_ids.add(dedupe_key)

            all_jobs.append(job)

        total_count = data.get("totalCount")
        page_size = data.get("limit") or len(jobs) or 20

        if not jobs:
            break

        if isinstance(total_count, int) and len(all_jobs) >= total_count:
            break

        # Search uses 1-based page pagination. If the API returns fewer than
        # its page size and no trustworthy total remains, this is the last page.
        if not isinstance(total_count, int) and len(jobs) < page_size:
            break

        page += 1

    if page > max_pages:
        raise RuntimeError(
            f"Himalayas pagination exceeded safety limit of {max_pages} pages"
        )

    return all_jobs


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


def _timestamp_to_iso(value):
    if value in (None, ""):
        return None

    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        try:
            value = float(value)
        except ValueError:
            return value

    if isinstance(value, (int, float)):
        # Himalayas documents pubDate/expiryDate as Unix milliseconds.
        if value > 10_000_000_000:
            value = value / 1000
        return datetime.fromtimestamp(
            value,
            tz=timezone.utc,
        ).isoformat()

    return None


def _location_to_text(raw_job):
    restrictions = raw_job.get("locationRestrictions") or []

    if not restrictions:
        return "Worldwide"

    rendered = []

    for item in restrictions:
        if isinstance(item, str):
            value = item.strip()
        elif isinstance(item, dict):
            value = (
                item.get("name")
                or item.get("alpha2")
                or item.get("slug")
                or ""
            )
            value = str(value).strip()
        else:
            value = ""

        if value and value not in rendered:
            rendered.append(value)

    return " | ".join(rendered) if rendered else "Worldwide"


def _salary_text(raw_job):
    minimum = raw_job.get("minSalary")
    maximum = raw_job.get("maxSalary")

    if minimum is None and maximum is None:
        return ""

    currency = str(raw_job.get("currency") or "").upper().strip()
    period = str(raw_job.get("salaryPeriod") or "annual").strip().lower()

    def render_amount(value):
        if isinstance(value, (int, float)):
            return f"{value:,.0f}"
        return str(value)

    if minimum is not None and maximum is not None:
        amount = f"{render_amount(minimum)}–{render_amount(maximum)}"
    elif minimum is not None:
        amount = f"{render_amount(minimum)}+"
    else:
        amount = f"Up to {render_amount(maximum)}"

    prefix = f"{currency} " if currency else ""
    return f"{prefix}{amount} per {period}"


def normalize_himalayas_job(raw_job):
    """Convert a Himalayas posting into VeeAys' common job structure."""
    description_parts = []

    excerpt = _html_to_text(raw_job.get("excerpt"))
    description = _html_to_text(raw_job.get("description"))

    if excerpt and excerpt not in description:
        description_parts.append(excerpt)

    if description:
        description_parts.append(description)

    employment_type = str(raw_job.get("employmentType") or "").strip()
    seniority = raw_job.get("seniority") or []
    categories = raw_job.get("categories") or []
    parent_categories = raw_job.get("parentCategories") or []
    timezone_restrictions = raw_job.get("timezoneRestrictions") or []
    salary = _salary_text(raw_job)

    metadata_lines = []
    if employment_type:
        metadata_lines.append(f"Employment type: {employment_type}")
    if seniority:
        metadata_lines.append("Seniority: " + ", ".join(map(str, seniority)))
    if categories:
        metadata_lines.append("Categories: " + ", ".join(map(str, categories)))
    if parent_categories:
        metadata_lines.append(
            "Job functions: " + ", ".join(map(str, parent_categories))
        )
    if timezone_restrictions:
        metadata_lines.append(
            "Timezone restrictions: "
            + ", ".join(map(str, timezone_restrictions))
        )
    if salary:
        metadata_lines.append(f"Compensation: {salary}")

    if metadata_lines:
        description_parts.append("\n".join(metadata_lines))

    guid = raw_job.get("guid")

    return {
        "title": raw_job.get("title") or "",
        "company": raw_job.get("companyName") or "Unknown",
        "company_logo_url": raw_job.get("companyLogo") or None,
        "description": "\n\n".join(description_parts).strip(),
        "category": None,
        "location": _location_to_text(raw_job),
        "remote": True,
        "workplace_type": "remote",
        "philippines_eligible": False,
        "source": "himalayas",
        "source_board": "philippines",
        "source_job_id": str(guid) if guid is not None else None,
        "job_url": raw_job.get("applicationLink"),
        "posted_at": _timestamp_to_iso(raw_job.get("pubDate")),
        "status": "active",
        "classification_reason": None,
    }
