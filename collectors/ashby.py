import requests


ASHBY_API_BASE = "https://api.ashbyhq.com/posting-api/job-board"


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
