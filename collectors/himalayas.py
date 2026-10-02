import html
import re
import time
from datetime import datetime, timezone

import requests


HIMALAYAS_SEARCH_API = "https://himalayas.app/jobs/api/search"
HIMALAYAS_SOURCE_URL = "https://himalayas.app"

HEADERS = {
    "User-Agent": "VeeAys/1.0",
    "Accept": "application/json",
}


def fetch_himalayas_jobs(
    country="PH",
    timeout=30,
    max_pages=200,
    request_delay=1.0,
    max_retries=5,
    return_metadata=False,
):
    """
    Fetch remote jobs eligible for a country from Himalayas' public API.

    The API can rate-limit long pagination runs. Requests are deliberately
    paced, HTTP 429 responses are retried with Retry-After when available,
    and a later-page failure returns the jobs already collected instead of
    discarding the entire source.

    When return_metadata=True, return (jobs, complete). ``complete`` is False
    whenever pagination had to stop because of a request/API/safety failure.
    Callers must not reconcile expired jobs from an incomplete fetch.
    """
    all_jobs = []
    seen_ids = set()
    page = 1
    complete = True

    while page <= max_pages:
        data = None

        for attempt in range(max_retries + 1):
            try:
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

                if response.status_code == 429:
                    if attempt >= max_retries:
                        print(
                            f"Himalayas page {page}: rate limit persisted "
                            f"after {max_retries + 1} attempts; keeping "
                            f"{len(all_jobs)} jobs already collected and "
                            "stopping safely."
                        )
                        complete = False
                        break

                    retry_after = response.headers.get("Retry-After")
                    try:
                        wait_seconds = float(retry_after)
                    except (TypeError, ValueError):
                        wait_seconds = min(60.0, 2 ** attempt * 5.0)

                    wait_seconds = max(1.0, wait_seconds)
                    print(
                        f"Himalayas page {page}: HTTP 429; waiting "
                        f"{wait_seconds:g}s before retry "
                        f"{attempt + 1}/{max_retries}."
                    )
                    time.sleep(wait_seconds)
                    continue

                response.raise_for_status()
                data = response.json()
                break

            except (requests.RequestException, ValueError) as error:
                if attempt >= max_retries:
                    print(
                        f"Himalayas page {page}: fetch failed after "
                        f"{max_retries + 1} attempts ({error}); keeping "
                        f"{len(all_jobs)} jobs already collected and "
                        "stopping safely."
                    )
                    complete = False
                    break

                wait_seconds = min(60.0, 2 ** attempt * 5.0)
                print(
                    f"Himalayas page {page}: request error ({error}); "
                    f"waiting {wait_seconds:g}s before retry "
                    f"{attempt + 1}/{max_retries}."
                )
                time.sleep(wait_seconds)

        if data is None:
            break

        if not isinstance(data, dict):
            print(
                f"Himalayas page {page}: unexpected API response; "
                f"keeping {len(all_jobs)} jobs already collected and "
                "stopping safely."
            )
            complete = False
            break

        jobs = data.get("jobs") or []
        if not isinstance(jobs, list):
            print(
                f"Himalayas page {page}: unexpected jobs payload; "
                f"keeping {len(all_jobs)} jobs already collected and "
                "stopping safely."
            )
            complete = False
            break

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

        if page == 1 or page % 10 == 0:
            print(
                f"Himalayas page {page}: "
                f"{len(all_jobs)} unique jobs collected"
            )

        total_count = data.get("totalCount")
        page_size = data.get("limit") or len(jobs) or 20

        if not jobs:
            break

        if isinstance(total_count, int) and len(all_jobs) >= total_count:
            break

        if not isinstance(total_count, int) and len(jobs) < page_size:
            break

        page += 1

        if request_delay:
            time.sleep(max(0.0, request_delay))

    if page > max_pages:
        print(
            f"Himalayas reached the safety limit of {max_pages} pages; "
            f"keeping {len(all_jobs)} jobs and skipping expiration "
            "reconciliation for this run."
        )
        complete = False

    if return_metadata:
        return all_jobs, complete

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
