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
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    return data.get("jobs", [])


def normalize_greenhouse_job(job, company, board):
    """
    Convert a Greenhouse job into our standard job format.
    """

    location = job.get("location", {}).get("name", "")

    return {
        "title": job.get("title"),
        "company": company,
        "description": job.get("content", ""),
        "location": location,
        "source": "greenhouse",
        "source_job_id": str(job.get("id")),
        "job_url": job.get("absolute_url"),
        "posted_at": job.get("updated_at"),
        "status": "active",
        "remote": "remote" in location.lower(),
    }
