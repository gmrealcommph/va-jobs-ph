import requests


LEVER_API_BASE = "https://api.lever.co/v0/postings"


def fetch_lever_jobs(company_slug):
    """
    Fetch all currently published jobs from a company's
    public Lever job board.

    Example:
        fetch_lever_jobs("companyname")
    """

    url = f"{LEVER_API_BASE}/{company_slug}"

    params = {
        "mode": "json",
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

    jobs = response.json()

    if not isinstance(jobs, list):
        raise ValueError(
            f"Unexpected Lever response for {company_slug}"
        )

    return jobs
