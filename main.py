import json
import os
import re
import html

from supabase import create_client
from collectors.greenhouse import (
    fetch_greenhouse_jobs,
    fetch_greenhouse_logo,
    normalize_greenhouse_job,
)
from collectors.lever import (
    fetch_lever_jobs,
    fetch_lever_company_logo,
)
from collectors.ashby import (
    fetch_ashby_jobs,
    fetch_ashby_company_logo,
)
from collectors.workable import (
    fetch_workable_jobs,
    fetch_workable_company_logo,
    normalize_workable_job,
)
from collectors.himalayas import (
    fetch_himalayas_jobs,
    normalize_himalayas_job,
)

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")


def load_greenhouse_boards():
    with open(
        "config/greenhouse_boards.json",
        "r",
        encoding="utf-8",
    ) as file:
        return json.load(file)

def load_lever_boards():
    with open(
        "config/lever_boards.json",
        "r",
        encoding="utf-8",
    ) as file:
        return json.load(file)

def load_ashby_boards():
    with open(
        "config/ashby_boards.json",
        "r",
        encoding="utf-8",
    ) as file:
        return json.load(file)


def load_workable_boards():
    with open(
        "config/workable_boards.json",
        "r",
        encoding="utf-8",
    ) as file:
        return json.load(file)

def normalize_ashby_job(
    raw_job,
    company,
    slug,
    company_logo_url=None,
):
    """
    Convert an Ashby job into the common structure used by
    our classifiers and Supabase jobs table.
    """

    location = raw_job.get("location") or ""

    description = (
        raw_job.get("descriptionPlain")
        or raw_job.get("description")
        or ""
    )

    job_id = raw_job.get("id")

    workplace_type = (
        raw_job.get("workplaceType")
        or ""
    ).strip()

    # Ashby workplaceType values include Remote, Hybrid,
    # and OnSite. Prefer this structured value when present.
    if workplace_type.lower() == "remote":
        remote = True

    elif workplace_type.lower() in {
        "hybrid",
        "onsite",
        "on-site",
    }:
        remote = False

    else:
        remote = raw_job.get("isRemote")

    return {
        "title": raw_job.get("title") or "",
        "company": company,
        "company_logo_url": company_logo_url,
        "description": description,
        "category": None,
        "location": location,
        "remote": remote,
        "workplace_type": workplace_type or "unspecified",
        "philippines_eligible": False,
        "source": "ashby",
        "source_board": slug,
        "source_job_id": (
            str(job_id)
            if job_id
            else None
        ),
        "job_url": (
            raw_job.get("jobUrl")
            or raw_job.get("applyUrl")
        ),
        "posted_at": raw_job.get("publishedAt"),
        "status": "active",
        "classification_reason": None,
    }
def normalize_lever_job(
    raw_job,
    company,
    slug,
    company_logo_url=None,
):
    """
    Convert a Lever job into the same structure used by our
    Greenhouse jobs and Supabase jobs table.

    Lever may split a posting across:
    - descriptionPlain / description / descriptionBody
    - lists
    - salaryRange
    - additionalPlain / additional

    Build one complete plain-text description from all
    available sections.
    """

    categories = (
        raw_job.get("categories")
        or {}
    )

    location = (
        categories.get("location")
        or ""
    )

    def html_to_text(value):
        """
        Convert Lever HTML into readable plain text while
        preserving useful headings, line breaks, and lists.
        """

        if not value:
            return ""

        text = str(value)

        text = re.sub(
            r"<br\s*/?>",
            "\n",
            text,
            flags=re.IGNORECASE,
        )

        text = re.sub(
            r"</(?:div|p|h[1-6])\s*>",
            "\n\n",
            text,
            flags=re.IGNORECASE,
        )

        text = re.sub(
            r"<li[^>]*>",
            "- ",
            text,
            flags=re.IGNORECASE,
        )

        text = re.sub(
            r"</li\s*>",
            "\n",
            text,
            flags=re.IGNORECASE,
        )

        text = re.sub(
            r"<[^>]+>",
            "",
            text,
        )

        text = html.unescape(text)

        text = text.replace(
            "\xa0",
            " ",
        )

        lines = [
            line.strip()
            for line in text.splitlines()
        ]

        cleaned_lines = []
        previous_blank = False

        for line in lines:
            is_blank = not line

            if (
                is_blank
                and previous_blank
            ):
                continue

            cleaned_lines.append(line)
            previous_blank = is_blank

        return "\n".join(
            cleaned_lines
        ).strip()

    description_parts = []

    # -------------------------------------------------
    # 1. Main description
    # -------------------------------------------------

    description_plain = (
        raw_job.get("descriptionPlain")
        or raw_job.get("descriptionBodyPlain")
        or ""
    ).strip()

    if description_plain:
        description_parts.append(
            description_plain
        )

    else:
        description_html = (
            raw_job.get("description")
            or raw_job.get("descriptionBody")
            or ""
        )

        description_text = html_to_text(
            description_html
        )

        if description_text:
            description_parts.append(
                description_text
            )

    # -------------------------------------------------
    # 2. Structured Lever sections
    # -------------------------------------------------

    lists = (
        raw_job.get("lists")
        or []
    )

    for section in lists:
        if not isinstance(
            section,
            dict,
        ):
            continue

        heading = (
            section.get("text")
            or ""
        ).strip()

        content = html_to_text(
            section.get("content")
            or ""
        )

        section_parts = []

        if heading:
            section_parts.append(
                heading
            )

        if content:
            section_parts.append(
                content
            )

        if section_parts:
            description_parts.append(
                "\n".join(
                    section_parts
                )
            )

    # -------------------------------------------------
    # 3. Compensation
    # -------------------------------------------------

    salary_range = (
        raw_job.get("salaryRange")
        or {}
    )

    if isinstance(
        salary_range,
        dict,
    ):
        minimum = salary_range.get(
            "min"
        )

        maximum = salary_range.get(
            "max"
        )

        currency = (
            salary_range.get("currency")
            or ""
        ).upper()

        interval = (
            salary_range.get("interval")
            or ""
        )

        interval_labels = {
            "per-year-salary":
                "per year",
            "per-month-salary":
                "per month",
            "per-week-salary":
                "per week",
            "per-day-salary":
                "per day",
            "per-hour-salary":
                "per hour",
        }

        interval_text = (
            interval_labels.get(
                interval,
                interval.replace(
                    "-salary",
                    "",
                ).replace(
                    "per-",
                    "per ",
                ).replace(
                    "-",
                    " ",
                ),
            )
        )

        salary_text = ""

        if (
            minimum is not None
            and maximum is not None
        ):
            salary_text = (
                f"{currency} "
                f"{minimum:,.0f}"
                f"–"
                f"{maximum:,.0f}"
            )

        elif minimum is not None:
            salary_text = (
                f"{currency} "
                f"{minimum:,.0f}+"
            )

        elif maximum is not None:
            salary_text = (
                f"Up to "
                f"{currency} "
                f"{maximum:,.0f}"
            )

        if salary_text:
            if interval_text:
                salary_text += (
                    f" {interval_text}"
                )

            description_parts.append(
                "Compensation\n"
                + salary_text
            )

    # -------------------------------------------------
    # 4. Additional information / benefits
    # -------------------------------------------------

    additional_plain = (
        raw_job.get("additionalPlain")
        or ""
    ).strip()

    if additional_plain:
        additional_text = (
            additional_plain
        )

    else:
        additional_html = (
            raw_job.get("additional")
            or ""
        )

        additional_text = html_to_text(
            additional_html
        )

    if additional_text:
        additional_lines = [
            line.strip()
            for line in additional_text.splitlines()
            if line.strip()
        ]

        if additional_lines:
            first_line = (
                additional_lines[0]
            )

            remaining_lines = (
                additional_lines[1:]
            )

            additional_parts = [
                first_line
            ]

            for line in remaining_lines:
                additional_parts.append(
                    f"- {line}"
                )

            description_parts.append(
                "\n".join(
                    additional_parts
                )
            )

    # -------------------------------------------------
    # Final combined description
    # -------------------------------------------------

    description = "\n\n".join(
        part.strip()
        for part in description_parts
        if part
        and part.strip()
    ).strip()

    job_id = raw_job.get("id")

    return {
        "title":
            raw_job.get("text")
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
            raw_job.get(
                "workplaceType"
            ) == "remote",

        "workplace_type":
            raw_job.get(
                "workplaceType",
                "unspecified",
            ),

        "philippines_eligible":
            False,

        "source":
            "lever",

        "source_board":
            slug,

        "source_job_id":
            (
                str(job_id)
                if job_id
                else None
            ),

        "job_url":
            (
                raw_job.get(
                    "hostedUrl"
                )
                or raw_job.get(
                    "applyUrl"
                )
            ),

        "posted_at":
            None,

        "status":
            "active",

        "classification_reason":
            None,
    }


def clean_text(value):
    if not value:
        return ""

    value = html.unescape(value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)

    return value.strip()

def check_remote_status(job):
    """
    Determine whether a job has sufficient evidence that it is remote.

    Returns:
        remote -> confirmed remote
        review -> remote status is unknown
        onsite -> confirmed non-remote
    """

    source = (
        job.get("source")
        or ""
    ).strip().lower()

    remote = job.get("remote")

    workplace_type = (
        job.get("workplace_type")
        or ""
    ).strip().lower()

    location = clean_text(
        job.get("location")
    ).lower()

    description = clean_text(
        job.get("description")
    ).lower()

    # ---------------------------------------------------------
    # 1. STRUCTURED WORKPLACE TYPE
    # ---------------------------------------------------------

    if workplace_type == "remote":
        return (
            "remote",
            "ATS explicitly indicates remote work",
        )

    if workplace_type in {
        "hybrid",
        "onsite",
        "on-site",
    }:
        return (
            "onsite",
            (
                "ATS explicitly indicates "
                f"{workplace_type} work"
            ),
        )

    # ---------------------------------------------------------
    # 2. STRUCTURED REMOTE FLAG
    # ---------------------------------------------------------

    if remote is True:
        return (
            "remote",
            "ATS explicitly marks job as remote",
        )

    # ---------------------------------------------------------
    # 3. TITLE EXPLICITLY INDICATES REMOTE WORK
    # ---------------------------------------------------------
    # Structured workplace_type above has priority, so wording in
    # a title can never override an explicit Hybrid/OnSite value.

    title = clean_text(
        job.get("title")
    ).lower()

    remote_title_patterns = [
        r"\bfully remote\b",
        r"\b100% remote\b",
        r"\bremote position\b",
        r"\bremote role\b",
        r"\bremote job\b",
        r"\(\s*remote\s*\)",
        r"(?:^|[-–—,|:/])\s*remote\b",
        r"\bremote\s*(?:[-–—,|:/]|$)",
    ]

    if any(
        re.search(pattern, title)
        for pattern in remote_title_patterns
    ):
        return (
            "remote",
            "Job title explicitly indicates remote work",
        )

    # ---------------------------------------------------------
    # 4. LOCATION EXPLICITLY INDICATES REMOTE WORK
    # ---------------------------------------------------------

    remote_location_terms = [
        "remote",
        "work from home",
        "work-from-home",
        "wfh",
        "home based",
        "home-based",
    ]

    if any(
        term in location
        for term in remote_location_terms
    ):
        return (
            "remote",
            "Location explicitly indicates remote work",
        )

    # ---------------------------------------------------------
    # 5. DESCRIPTION EXPLICITLY CONFIRMS REMOTE WORK
    # ---------------------------------------------------------

    explicit_remote_phrases = [
        "this is a remote position",
        "this is a fully remote position",
        "this is a 100% remote position",
        "this is a remote role",
        "this is a fully remote role",
        "fully remote position",
        "fully remote role",
        "100% remote position",
        "100% remote role",
        "work from home position",
        "work-from-home position",
        "work from home role",
        "work-from-home role",
        "home-based position",
        "home based position",
        "home-based role",
        "home based role",
    ]

    if any(
        phrase in description
        for phrase in explicit_remote_phrases
    ):
        return (
            "remote",
            (
                "Job description explicitly "
                "confirms remote work"
            ),
        )

    # ---------------------------------------------------------
    # 6. EXPLICIT NON-REMOTE FLAG
    # ---------------------------------------------------------
    #
    # Ashby exposes a meaningful structured remote flag.
    # For Greenhouse, remote=False is inferred by our own
    # normalizer when no remote wording was found, so it must
    # NOT automatically mean onsite.

    if source == "ashby" and remote is False:
        return (
            "onsite",
            "ATS explicitly marks job as non-remote",
        )

    # ---------------------------------------------------------
    # 7. REMOTE STATUS UNKNOWN
    # ---------------------------------------------------------

    return (
        "review",
        "Remote status is not specified",
    )


def check_philippines_eligibility(job):
    """
    Determine whether Philippines-based applicants are eligible.

    Evidence priority:
    1. Explicit Philippines location
    2. APAC / Southeast Asia location
    3. Worldwide/global location
    4. Explicit description restrictions that exclude the Philippines
    5. Contextual description evidence that includes the Philippines,
       APAC/Southeast Asia, or worldwide/global applicants
    6. Generic/blank remote locations remain review
    7. Other explicit locations are rejected

    Merely mentioning "Philippines" somewhere in the description is not
    enough. Description matches require contextual hiring/location language.
    """

    location = clean_text(
        job.get("location")
    ).lower().strip()

    description = clean_text(
        job.get("description")
    ).lower().strip()

    philippines_terms = [
        "philippines",
        "philippine",
        "metro manila",
        "manila",
        "makati",
        "taguig",
        "quezon city",
        "pasig",
        "cebu",
        "davao",
    ]

    if any(
        term in location
        for term in philippines_terms
    ):
        return (
            "publish",
            "Location explicitly allows Philippines",
        )

    apac_terms = [
        "apac",
        "asia pacific",
        "asia-pacific",
        "southeast asia",
        "south east asia",
    ]

    if any(
        term in location
        for term in apac_terms
    ):
        return (
            "publish",
            "Location explicitly allows APAC/Asia applicants",
        )

    worldwide_terms = [
        "worldwide",
        "anywhere",
        "global",
        "remote - global",
        "remote-global",
        "remote worldwide",
        "remote - worldwide",
    ]

    if any(
        term in location
        for term in worldwide_terms
    ):
        return (
            "publish",
            "Location explicitly allows worldwide applicants",
        )

    # ---------------------------------------------------------
    # STRUCTURED LOCATION PRECEDENCE
    # ---------------------------------------------------------
    # Description-based geography rescue is intended for ambiguous
    # ATS locations (blank, Remote, etc.). A concrete non-PH ATS
    # country/region must not be overridden by generic wording such
    # as "global company" or "worldwide team" in the description.

    generic_remote = [
        "remote",
        "fully remote",
        "remote - remote",
    ]

    ambiguous_location = (
        not location
        or location in generic_remote
        or location in {
            "work from home",
            "work-from-home",
            "wfh",
            "home based",
            "home-based",
        }
    )

    # ---------------------------------------------------------
    # DESCRIPTION: EXPLICIT RESTRICTIONS
    # ---------------------------------------------------------
    # These patterns are deliberately conservative. They target
    # common wording that explicitly limits where the candidate
    # may live/work. This check runs before positive description
    # evidence so a posting such as "global company, US applicants
    # only" cannot be published because of the word "global".

    exclusion_patterns = [
        (
            r"\b(?:candidates?|applicants?|employees?|hires?)\b"
            r".{0,80}\b(?:must|need to|required to)\b"
            r".{0,50}\b(?:reside|live|be based|be located|work)\b"
            r".{0,50}\b(?:in|within)\s+"
            r"(?:the\s+)?(?:united states|u\.?s\.?a?|usa|canada|"
            r"united kingdom|u\.?k\.?|uk|australia|new zealand|"
            r"india|mexico|brazil|south africa|europe|emea|latam)\b"
        ),
        (
            r"\b(?:only|exclusively)\s+(?:open\s+to\s+)?"
            r"(?:candidates?|applicants?|residents?|hires?)?"
            r".{0,50}\b(?:in|from|within|based in|located in)\s+"
            r"(?:the\s+)?(?:united states|u\.?s\.?a?|usa|canada|"
            r"united kingdom|u\.?k\.?|uk|australia|new zealand|"
            r"india|mexico|brazil|south africa|europe|emea|latam)\b"
        ),
        (
            r"\b(?:united states|u\.?s\.?a?|usa|canada|"
            r"united kingdom|u\.?k\.?|uk|australia|new zealand|"
            r"india|mexico|brazil|south africa|europe|emea|latam)"
            r"[- ]only\b"
        ),
        (
            r"\bremote\s+(?:within|in|from)\s+"
            r"(?:the\s+)?(?:united states|u\.?s\.?a?|usa|canada|"
            r"united kingdom|u\.?k\.?|uk|australia|new zealand|"
            r"india|mexico|brazil|south africa|europe|emea|latam)\b"
        ),
    ]

    if description and any(
        re.search(pattern, description)
        for pattern in exclusion_patterns
    ):
        return (
            "reject",
            "Job description explicitly restricts hiring to a non-Philippines location",
        )

    # ---------------------------------------------------------
    # DESCRIPTION: PHILIPPINES ELIGIBILITY
    # ---------------------------------------------------------
    # Require the Philippines to appear near contextual words that
    # indicate candidate location/hiring eligibility. This avoids
    # publishing a job merely because a company mentions an office,
    # customer, market, or unrelated Philippine reference.

    ph_context_patterns = [
        r"\b(?:open to|hiring|hire|recruiting|seeking|looking for)"
        r".{0,100}\b(?:candidates?|applicants?|talent|people|professionals?)"
        r".{0,100}\b(?:in|from|based in|located in)?\s*(?:the\s+)?philippines\b",
        r"\b(?:candidates?|applicants?|talent|people|professionals?)"
        r".{0,100}\b(?:in|from|based in|located in|residing in)\s+"
        r"(?:the\s+)?philippines\b",
        r"\b(?:must|should|need to|required to)\b"
        r".{0,60}\b(?:reside|live|be based|be located)\b"
        r".{0,60}\b(?:in\s+)?(?:the\s+)?philippines\b",
        r"\b(?:philippines|philippine)[- ]based\b",
        r"\bbased\s+in\s+(?:the\s+)?philippines\b",
        r"\blocated\s+in\s+(?:the\s+)?philippines\b",
        r"\bremote\s+(?:in|from|within)\s+(?:the\s+)?philippines\b",
        r"\bwork\s+(?:remotely\s+)?from\s+(?:the\s+)?philippines\b",
        r"\b(?:location|work location|candidate location)\s*[:\-]\s*"
        r"(?:remote\s*[-,/]\s*)?(?:the\s+)?philippines\b",
    ]

    if ambiguous_location and description and any(
        re.search(pattern, description)
        for pattern in ph_context_patterns
    ):
        return (
            "publish",
            "Job description explicitly allows Philippines applicants",
        )

    # ---------------------------------------------------------
    # DESCRIPTION: APAC / SOUTHEAST ASIA ELIGIBILITY
    # ---------------------------------------------------------

    asia_region = (
        r"(?:apac|asia[- ]pacific|southeast asia|south east asia)"
    )

    apac_context_patterns = [
        rf"\b(?:open to|hiring|hire|recruiting|seeking|looking for)"
        rf".{{0,100}}\b(?:candidates?|applicants?|talent|people|professionals?)"
        rf".{{0,100}}\b(?:in|from|across|within)?\s*{asia_region}\b",
        rf"\b(?:candidates?|applicants?|talent|people|professionals?)"
        rf".{{0,100}}\b(?:in|from|across|within|based in|located in)\s+"
        rf"{asia_region}\b",
        rf"\b(?:remote|work remotely)\s+(?:in|from|within|across)\s+"
        rf"{asia_region}\b",
        rf"\b(?:location|work location|candidate location)\s*[:\-]\s*"
        rf"(?:remote\s*[-,/]\s*)?{asia_region}\b",
    ]

    if ambiguous_location and description and any(
        re.search(pattern, description)
        for pattern in apac_context_patterns
    ):
        return (
            "publish",
            "Job description explicitly allows APAC/Southeast Asia applicants",
        )

    # ---------------------------------------------------------
    # DESCRIPTION: WORLDWIDE / GLOBAL ELIGIBILITY
    # ---------------------------------------------------------

    worldwide_context_patterns = [
        r"\b(?:open to|hiring|hire|recruiting|seeking)"
        r".{0,100}\b(?:candidates?|applicants?|talent|people|professionals?)"
        r".{0,100}\b(?:worldwide|globally|anywhere in the world)\b",
        r"\b(?:candidates?|applicants?|talent|people|professionals?)"
        r".{0,100}\b(?:worldwide|globally|from anywhere|anywhere in the world)\b",
        r"\bwork\s+from\s+anywhere\b",
        r"\bremote\s+(?:worldwide|globally)\b",
        r"\bglobally\s+remote\b",
        r"\b(?:location|work location|candidate location)\s*[:\-]\s*"
        r"(?:worldwide|global|anywhere)\b",
    ]

    if ambiguous_location and description and any(
        re.search(pattern, description)
        for pattern in worldwide_context_patterns
    ):
        return (
            "publish",
            "Job description explicitly allows worldwide applicants",
        )

    if location in generic_remote or not location:
        return (
            "review",
            "Remote/location eligibility is ambiguous",
        )

    return (
        "reject",
        f"No explicit Philippines eligibility: {job.get('location')}",
    )

def check_active_vacancy(job):
    """
    Detect postings that are talent pools, future opportunities,
    expressions of interest, or otherwise not active vacancies.

    Returns:
        active -> appears to be a current vacancy
        reject -> explicitly not a current vacancy
    """

    title = clean_text(job.get("title")).lower()
    description = clean_text(job.get("description")).lower()

    # ---------------------------------------------------------
    # STRONG TITLE SIGNALS
    # ---------------------------------------------------------

    non_active_title_terms = [
        "talent pool",
        "talent community",
        "future opportunities",
        "future opportunity",
        "expression of interest",
        "expressions of interest",
        "general application",
        "general applications",
    ]

    if any(term in title for term in non_active_title_terms):
        return (
            "reject",
            "Posting is a talent pool or future-opportunity listing",
        )

    # ---------------------------------------------------------
    # STRONG DESCRIPTION SIGNALS
    # ---------------------------------------------------------

    non_active_description_phrases = [
        "this is not an active job opening",
        "this is not an active opening",
        "this is not a current job opening",
        "this is not a current opening",
        "not currently an active opening",
        "not currently hiring for this role",
        "we are not currently hiring for this role",
        "this posting is for future opportunities",
        "this role is for future opportunities",
        "this posting is for future openings",
        "join our talent pool",
        "join our talent community",
        "expression of interest for future",
    ]

    if any(
        phrase in description
        for phrase in non_active_description_phrases
    ):
        return (
            "reject",
            "Posting explicitly states it is not a current vacancy",
        )

    return (
        "active",
        "Posting appears to be an active vacancy",
    )

def check_va_relevance(job):
    """
    Decide whether a geographically eligible job belongs on the
    Philippines-focused VA / remote-work platform.

    Returns:
        relevant   -> publish automatically
        review     -> potentially suitable but genuinely ambiguous
        irrelevant -> reject automatically
    """

    title = clean_text(job.get("title")).lower()

    # ---------------------------------------------------------
    # 1. EXPLICIT VIRTUAL ASSISTANT ROLES
    # ---------------------------------------------------------
    # Protect genuine VA titles before technical exclusions.
    # Some VA jobs legitimately include technical, ecommerce,
    # automation, or digital-infrastructure responsibilities.

    explicit_va_terms = [
        "virtual assistant",
        "virtual administrative assistant",
        "virtual executive assistant",
    ]

    if any(term in title for term in explicit_va_terms):
        return (
            "relevant",
            "Title explicitly identifies a virtual assistant role",
        )

    # ---------------------------------------------------------
    # 2. TECHNICAL / SPECIALIST ROLES WE DON'T WANT
    # ---------------------------------------------------------

    technical_exclusions = [
        # Engineering / development
        "engineer",
        "engineering",
        "developer",
        "software developer",
        "software development",
        "web developer",
        "frontend developer",
        "front-end developer",
        "backend developer",
        "back-end developer",
        "full stack",
        "full-stack",
        "golang",
        "python developer",
        "python engineer",
        "rust developer",
        "rust engineer",

        # Technical writing
        "technical author",

        # Technical account / customer success
        "technical account manager",
        "technical customer success",

        # Technical project management
        "it project manager",

        # Infrastructure / cloud / embedded
        "devops",
        "site reliability",
        "linux",
        "kernel",
        "cloud architect",
        "solutions architect",
        "solution architect",
        "systems architect",
        "openstack",
        "kubernetes",
        "containerization",
        "virtualisation",
        "virtualization",
        "embedded systems",
        "embedded devices",
        "embedded software",
        "ubuntu",

        # Security
        "security engineer",
        "security researcher",
        "security operations",
        "cybersecurity",
        "threat intelligence",

        # Data / AI
        "data scientist",
        "machine learning",
        "mlops",
        "research scientist",

        # Legal
        "legal counsel",
        "general counsel",
        "attorney",
        "lawyer",

        # Medical / clinical
        "physician",
        "nurse",
        "clinical",

        # Highly technical relations
        "developer relations",
        "developer advocate",
    ]

    if any(term in title for term in technical_exclusions):
        return (
            "irrelevant",
            "Technical/professional role outside VA job scope",
        )

    # ---------------------------------------------------------
    # 3. SENIOR LEADERSHIP / SENIOR PROJECT ROLES
    # ---------------------------------------------------------

    senior_terms = [
        "vice president",
        "vp ",
        "vp,",
        "director",
        "head of ",
        "principal ",
        "chief ",
        "senior manager",
        "general manager",
        "team manager",
        "senior project manager",
        "enterprise project manager",
    ]

    if any(term in title for term in senior_terms):
        return (
            "irrelevant",
            "Senior leadership role outside target job scope",
        )

    # ---------------------------------------------------------
    # 4. SPECIALIZED ENTERPRISE / PARTNER SALES
    # ---------------------------------------------------------

    enterprise_sales_exclusions = [
        "enterprise account executive",
        "strategic account executive",
        "commercial account executive",
        "channel partner",
        "channel sales",
        "partner sales",
        "alliance sales",
        "alliances sales",
        "global account executive",
        "enterprise sales",
        "solution sales",
        "solutions sales",
    ]

    if any(
        term in title
        for term in enterprise_sales_exclusions
    ):
        return (
            "irrelevant",
            (
                "Specialized enterprise/partner sales role "
                "outside target scope"
            ),
        )

    # ---------------------------------------------------------
    # 5. HIGH-CONFIDENCE TARGET ROLES
    # ---------------------------------------------------------

    target_terms = [
        # Executive / administrative assistance
        "executive assistant",
        "personal assistant",
        "administrative assistant",
        "admin assistant",
        "administrative coordinator",
        "admin coordinator",
        "sales administrator",
        "sourcing admin",
        "recruitment and sourcing admin",
        "office coordinator",
        "office assistant",
        "remote assistant",
        "office administrator",
        "property management assistant",
        "service coordinator",

        # Customer service / support
        "customer support",
        "customer service",
        "customer experience",
        "customer care",
        "support specialist",
        "support representative",
        "support agent",
        "customer service representative",
        "onboarding associate",
        "onboarding specialist",
        "onboarding expert",
        "onboarding coordinator",
        "onboarding documents associate",

        # Customer success
        "customer success",

        # Entry/mid-level sales & lead generation
        "sales development representative",
        "sales development",
        "business development representative",
        "business development",
        "appointment setter",
        "lead generation",
        "lead generator",
        "sales representative",
        "inside sales",
        "sales associate",

        # Operations / coordination
        "operations assistant",
        "operations coordinator",
        "operations specialist",
        "operations manager",
        "project coordinator",
        "project assistant",
        "business operations coordinator",

        # Project management
        "junior project manager",
        "project manager",

        # Marketing
        "marketing assistant",
        "marketing associate",
        "marketing coordinator",
        "marketing specialist",
        "marketing manager",
        "digital marketing",
        "email marketing",
        "lifecycle marketer",
        "media buyer",
        "ppc manager",
        "seo specialist",
        "seo assistant",
        "growth marketer",
        "performance marketer",
        "paid media specialist",
        "google ads specialist",

        # Social / community
        "social media",
        "community manager",
        "community specialist",
        "content creator",

        # E-commerce
        "ecommerce",
        "e-commerce",
        "shopify",
        "amazon specialist",
        "amazon virtual assistant",
        "amazon account specialist",
        "amazon ppc specialist",
        "amazon listing content specialist",

        # Bookkeeping / finance support
        "bookkeeper",
        "bookkeeping",
        "accounting assistant",
        "accounts payable",
        "accounts receivable",
        "billing specialist",
        "billing representative",
        "medical biller",
        "scheduling coordinator",
        "records coordinator",
        "payroll specialist",
        "accountant",
        "accounting specialist",
        "finance specialist",
        "finance assistant",
        "accounts officer",

        # Recruitment / HR
        "recruiter",
        "staffing specialist",
        "recruitment coordinator",
        "talent acquisition coordinator",
        "hr assistant",
        "hr coordinator",
        "hr specialist",
        "hr generalist",
        "human resources assistant",
        "talent acquisition specialist",
        "talent acquisition associate",
        "recruitment specialist",

        # Writing / content
        "copywriter",
        "content writer",
        "content editor",
        "blog writer",

        # Design / creative
        "graphic designer",
        "video editor",
        "motion designer",
        "digital designer",
        "production designer",
        "graphics designer",

        # Data/admin
        "data entry",
        "data encoder",
        "data processor",

        # Account/client management
        "account manager",
    ]

    abbreviation_patterns = [
        r"\bsdr\b",
        r"\bbdr\b",
    ]

    matches_target = (
        any(term in title for term in target_terms)
        or any(
            re.search(pattern, title)
            for pattern in abbreviation_patterns
        )
    )

    if matches_target:
        return (
            "relevant",
            "Title matches target VA/remote-work role",
        )

    # ---------------------------------------------------------
    # 6. GENUINELY AMBIGUOUS ROLES
    # ---------------------------------------------------------

    review_terms = [
        "mobility specialist",
        "content specialist",
        "communications specialist",
        "communications coordinator",
        "human resources",
        "talent acquisition",
        "business services",
        "account coordinator",
        "account specialist",
    ]

    if any(term in title for term in review_terms):
        return (
            "review",
            "Potential remote-work role requires review",
        )

    # ---------------------------------------------------------
    # 7. DESCRIPTION-BASED ROLE RESCUE
    # ---------------------------------------------------------
    # Title matching remains the primary signal. Only titles that
    # have NOT already matched our target, technical, leadership,
    # or specialized-sales rules reach this section.
    #
    # Rescue requires evidence across multiple responsibility
    # groups. Repeating one generic phrase such as "customer
    # support" is not enough to publish an otherwise unknown role.

    description = clean_text(
        job.get("description")
    ).lower()

    responsibility_groups = {
        "admin": [
            "calendar management",
            "manage calendars",
            "manage calendar",
            "schedule meetings",
            "scheduling meetings",
            "coordinate meetings",
            "meeting coordination",
            "manage inbox",
            "inbox management",
            "email management",
            "manage emails",
            "administrative support",
            "administrative tasks",
            "travel arrangements",
            "travel coordination",
            "prepare reports",
            "prepare documents",
            "document preparation",
        ],
        "customer_support": [
            "respond to customer inquiries",
            "respond to customer enquiries",
            "customer inquiries",
            "customer enquiries",
            "customer support",
            "customer service",
            "customer experience",
            "resolve customer issues",
            "customer complaints",
            "support tickets",
            "ticketing system",
            "live chat",
            "email support",
            "chat support",
        ],
        "sales_lead_gen": [
            "lead generation",
            "prospecting",
            "cold outreach",
            "cold calling",
            "appointment setting",
            "book appointments",
            "qualify leads",
            "sales pipeline",
            "crm management",
            "update crm",
            "manage crm",
            "follow up with leads",
            "sales outreach",
        ],
        "operations": [
            "operational support",
            "operations support",
            "coordinate projects",
            "project coordination",
            "task coordination",
            "process documentation",
            "standard operating procedures",
            "manage workflows",
            "workflow management",
            "data management",
            "database management",
            "record keeping",
            "maintain records",
        ],
        "marketing_social": [
            "social media management",
            "manage social media",
            "social media posts",
            "schedule social media",
            "content calendar",
            "content scheduling",
            "email campaigns",
            "email marketing",
            "marketing campaigns",
            "marketing support",
            "seo",
            "keyword research",
            "community engagement",
        ],
        "ecommerce": [
            "shopify",
            "amazon seller",
            "product listings",
            "product listing",
            "e-commerce",
            "ecommerce",
            "order processing",
            "order management",
            "inventory management",
            "customer orders",
        ],
        "finance_bookkeeping": [
            "bookkeeping",
            "accounts payable",
            "accounts receivable",
            "invoice processing",
            "process invoices",
            "bank reconciliation",
            "reconcile accounts",
            "payroll processing",
            "financial records",
            "expense tracking",
        ],
        "recruiting_hr": [
            "candidate sourcing",
            "source candidates",
            "screen candidates",
            "candidate screening",
            "schedule interviews",
            "interview scheduling",
            "recruitment support",
            "recruiting support",
            "onboarding employees",
            "employee onboarding",
            "hr administration",
        ],
        "content_creative": [
            "write blog",
            "blog posts",
            "copywriting",
            "content writing",
            "edit videos",
            "video editing",
            "graphic design",
            "design graphics",
            "create graphics",
            "content creation",
        ],
    }

    matched_groups = []

    if description:
        for group_name, phrases in responsibility_groups.items():
            if any(
                phrase in description
                for phrase in phrases
            ):
                matched_groups.append(group_name)

    # Three distinct responsibility groups is strong enough to
    # rescue an otherwise-unrecognized title automatically.
    if len(matched_groups) >= 3:
        return (
            "relevant",
            (
                "Description strongly matches target remote-work "
                "responsibilities across multiple areas: "
                + ", ".join(matched_groups[:5])
            ),
        )

    # Two distinct groups is meaningful but still ambiguous.
    # Send these to Review rather than publishing automatically.
    if len(matched_groups) == 2:
        return (
            "review",
            (
                "Description suggests target remote-work "
                "responsibilities but requires review: "
                + ", ".join(matched_groups)
            ),
        )

    # ---------------------------------------------------------
    # 8. EVERYTHING ELSE
    # ---------------------------------------------------------

    return (
        "irrelevant",
        "Role does not match target VA/remote-work categories",
    )



def classify_job(job):
    """
    Categorize primarily using the job title.

    More specific categories are checked before broader categories
    so mixed-role titles land in the most useful category.
    """

    title = clean_text(job.get("title")).lower()

    categories = [
        (
            "Virtual Assistant",
            [
                "virtual assistant",
                "remote assistant",
            ],
        ),
        (
            "Executive Assistant",
            [
                "executive assistant",
                "personal assistant",
                "administrative assistant",
                "admin assistant",
                "office administrator",
                "property management assistant",
            ],
        ),
        (
            "Customer Support",
            [
                "customer support",
                "customer service",
                "support specialist",
                "support representative",
                "billing representative",
                "onboarding associate",
                "onboarding specialist",
                "onboarding expert",
                "onboarding coordinator",
                "onboarding documents associate",
                "customer success",
                "customer experience",
                "medical biller",
                "scheduling coordinator",
                "records coordinator",
            ],
        ),
        (
            "Sales",
            [
                "sales",
                "business development",
                "appointment setter",
                "lead generation",
                "account executive",
                "sdr",
                "bdr",
            ],
        ),

        # Social Media must be checked before Marketing.
        (
            "Social Media",
            [
                "social media",
                "community manager",
                "content creator",
            ],
        ),
        (
            "Marketing",
            [
                "marketing",
                "growth marketing",
                "lifecycle marketer",
                "media buyer",
                "ppc manager",
                "seo",
                "email marketer",
                "performance marketer",
                "paid media specialist",
                "google ads specialist",
            ],
        ),
        (
            "E-commerce",
            [
                "ecommerce",
                "e-commerce",
                "shopify",
                "amazon specialist",
                "amazon account specialist",
                "amazon ppc specialist",
                "amazon listing content specialist",
            ],
        ),
        (
            "Bookkeeping & Finance",
            [
                "bookkeeper",
                "bookkeeping",
                "accounting",
                "accounts payable",
                "accounts receivable",
                "finance",
                "payroll",
                "accountant",
                "finance assistant",
                "finance specialist",
            ],
        ),
        (
            "Recruitment & HR",
            [
                "recruiter",
                "recruitment",
                "staffing specialist",
                "sourcing admin",
                "talent acquisition",
                "human resources",
                "hr specialist",
                "hr coordinator",
                "people operations",
                "hr assistant",
                "hr generalist",
                "talent acquisition specialist",
                "talent acquisition associate",
                "recruitment specialist",
            ],
        ),
        (
            "Design & Creative",
            [
                "graphic designer",
                "designer",
                "video editor",
                "motion designer",
                "digital designer",
                "production designer",
                "graphics designer",
            ],
        ),
        (
            "Writing & Content",
            [
                "copywriter",
                "content writer",
                "writer",
                "editor",
            ],
        ),
        (
            "Data Entry",
            [
                "data entry",
                "data encoder",
            ],
        ),
        (
            "Project Management",
            [
                "project manager",
                "project management",
            ],
        ),
        (
            "Account Management",
            [
                "account manager",
                "client account manager",
                "client success manager",
            ],
        ),
        (
            "Operations & Admin",
            [
                "operations",
                "operations specialist",
                "operations coordinator",
                "project coordinator",
                "administrative",
                "sales administrator",
            ],
        ),
    ]

    for category, keywords in categories:
        if any(keyword in title for keyword in keywords):
            return category

    return "Other Remote"


def save_published_job(supabase, job, reason):
    job["philippines_eligible"] = True
    job["classification_reason"] = reason
    job["category"] = classify_job(job)

    # Publish/update the job.
    (
        supabase.table("jobs")
        .upsert(
            job,
            on_conflict="source,source_job_id",
        )
        .execute()
    )

    # If this job was previously waiting in Review/Rejected,
    # remove that stale classification.
    (
        supabase.table("job_reviews")
        .delete()
        .eq("source", job.get("source"))
        .eq("source_job_id", job.get("source_job_id"))
        .execute()
    )


def save_review_job(supabase, job, decision, reason):
    record = {
        "title": job.get("title"),
        "company": job.get("company"),
        "location": job.get("location"),
        "source": job.get("source"),
        "source_job_id": job.get("source_job_id"),
        "job_url": job.get("job_url"),
        "decision": decision,
        "reason": reason,
    }

    # Store/update the latest review or rejection decision.
    (
        supabase.table("job_reviews")
        .upsert(
            record,
            on_conflict="source,source_job_id",
        )
        .execute()
    )

    # If this job was previously published, remove the stale
    # published copy so it cannot remain visible on the site.
    (
        supabase.table("jobs")
        .delete()
        .eq("source", job.get("source"))
        .eq("source_job_id", job.get("source_job_id"))
        .execute()
    )

def flush_job_batches(
    supabase,
    published_jobs,
    review_jobs,
    batch_size=200,
):
    """
    Write classified jobs to Supabase in batches.

    Published jobs belong in public.jobs.
    Review/rejected jobs belong in public.job_reviews.

    Also removes stale records from the opposite table.
    """

    def chunks(items, size):
        for i in range(0, len(items), size):
            yield items[i:i + size]

    def deduplicate_upsert_records(records):
        """
        Ensure a single Supabase upsert never contains the same
        (source, source_job_id) conflict key more than once.

        Some ATS feeds can expose the same underlying posting more
        than once, such as one posting attached to multiple locations.
        Postgres rejects duplicate conflict keys inside one
        INSERT ... ON CONFLICT statement.

        Last record wins so the result is deterministic.
        """
        deduplicated = {}
        records_without_key = []

        for record in records:
            source = record.get("source")
            source_job_id = record.get("source_job_id")

            if source and source_job_id:
                key = (str(source), str(source_job_id))
                deduplicated[key] = record
            else:
                records_without_key.append(record)

        return list(deduplicated.values()) + records_without_key

    original_published_count = len(published_jobs)
    original_review_count = len(review_jobs)

    published_jobs = deduplicate_upsert_records(published_jobs)
    review_jobs = deduplicate_upsert_records(review_jobs)

    removed_published_duplicates = (
        original_published_count - len(published_jobs)
    )
    removed_review_duplicates = (
        original_review_count - len(review_jobs)
    )

    print("\n================================")
    print("WRITING DATABASE BATCHES")
    print("================================")
    print(
        f"Duplicate published records removed: "
        f"{removed_published_duplicates}"
    )
    print(
        f"Duplicate review/rejected records removed: "
        f"{removed_review_duplicates}"
    )

    # -----------------------------------------------------
    # PUBLISHED JOBS
    # -----------------------------------------------------

    for batch in chunks(published_jobs, batch_size):
        (
            supabase.table("jobs")
            .upsert(
                batch,
                on_conflict="source,source_job_id",
            )
            .execute()
        )

    # -----------------------------------------------------
    # REVIEW / REJECTED JOBS
    # -----------------------------------------------------

    for batch in chunks(review_jobs, batch_size):
        (
            supabase.table("job_reviews")
            .upsert(
                batch,
                on_conflict="source,source_job_id",
            )
            .execute()
        )

    # -----------------------------------------------------
    # REMOVE STALE CROSS-TABLE RECORDS IN BATCHES
    # -----------------------------------------------------

    def batch_delete_opposite_table(
        table_name,
        records,
        size,
    ):
        """
        Delete stale records from the opposite table.

        Records are grouped by source first so that a job ID
        from one ATS can never accidentally match the same ID
        from another ATS.
        """

        records_by_source = {}

        for record in records:
            source = record.get("source")
            source_job_id = record.get("source_job_id")

            if not source or not source_job_id:
                continue

            records_by_source.setdefault(
                source,
                [],
            ).append(source_job_id)

        for source, job_ids in records_by_source.items():

            # Remove duplicate IDs before sending requests.
            job_ids = list(dict.fromkeys(job_ids))

            for id_batch in chunks(job_ids, size):
                (
                    supabase.table(table_name)
                    .delete()
                    .eq("source", source)
                    .in_("source_job_id", id_batch)
                    .execute()
            )


    # Published jobs must not remain in job_reviews.
    batch_delete_opposite_table(
        "job_reviews",
        published_jobs,
        batch_size,
    )

    # Review/rejected jobs must not remain published.
    batch_delete_opposite_table(
        "jobs",
        review_jobs,
        batch_size,
    )

    print(
        f"Published batch records: "
        f"{len(published_jobs)}"
    )

    print(
        f"Review/rejected batch records: "
        f"{len(review_jobs)}"
    )

def get_live_inventory_count(supabase):
    """
    Return the authoritative live inventory count used for launch tracking.

    Prefer the public_jobs view because that is the frontend-facing dataset.
    If that view is unavailable for any reason, fall back to active rows in
    public.jobs and label the fallback accurately.
    """

    try:
        response = (
            supabase.table("public_jobs")
            .select("*", count="exact", head=True)
            .execute()
        )

        if response.count is not None:
            return response.count, "Visible jobs (public_jobs)"

    except Exception as error:
        print(
            "Could not count public_jobs view; "
            f"falling back to active jobs table rows: {error}"
        )

    try:
        response = (
            supabase.table("jobs")
            .select("*", count="exact", head=True)
            .eq("status", "active")
            .execute()
        )

        if response.count is not None:
            return response.count, "Active jobs in DB"

    except Exception as error:
        print(f"Could not count active jobs in DB: {error}")

    return None, "Active jobs in DB"


def reconcile_expired_jobs(
    supabase,
    successful_boards,
    batch_size=200,
):
    """
    Mark published jobs inactive when they disappear from a
    successfully fetched ATS board.

    Safety rules:
    - Only reconcile boards that fetched successfully.
    - Scope every comparison to source + source_board.
    - Never expire anything when a board fetch failed.
    - Never expire anything when the current board returned zero jobs.
      A zero-job response is treated conservatively.
    """

    print("\n================================")
    print("RECONCILING EXPIRED JOBS")
    print("================================")

    total_expired = 0

    for board_data in successful_boards:
        source = board_data["source"]
        source_board = board_data["source_board"]
        current_job_ids = board_data["job_ids"]

        # -----------------------------------------------------
        # SAFETY: DON'T CLEAN A BOARD THAT RETURNED ZERO JOBS
        # -----------------------------------------------------

        if not current_job_ids:
            print(
                f"  SKIPPED: {source}/{source_board} "
                f"returned zero jobs."
            )
            continue

        try:
            # Get currently stored published jobs for this exact board.
            response = (
                supabase.table("jobs")
                .select("source_job_id,status")
                .eq("source", source)
                .eq("source_board", source_board)
                .execute()
            )

            stored_jobs = response.data or []

            current_job_ids = {
                str(job_id)
                for job_id in current_job_ids
                if job_id is not None
            }

            stale_job_ids = [
                str(record.get("source_job_id"))
                for record in stored_jobs
                if record.get("source_job_id") is not None
                and str(record.get("source_job_id"))
                not in current_job_ids
                and record.get("status") != "inactive"
            ]

            if not stale_job_ids:
                print(
                    f"  {source}/{source_board}: "
                    f"0 expired jobs."
                )
                continue

            # Mark stale jobs inactive in manageable batches.
            for start in range(
                0,
                len(stale_job_ids),
                batch_size,
            ):
                id_batch = stale_job_ids[
                    start:start + batch_size
                ]

                (
                    supabase.table("jobs")
                    .update({"status": "inactive"})
                    .eq("source", source)
                    .eq("source_board", source_board)
                    .in_("source_job_id", id_batch)
                    .execute()
                )

            total_expired += len(stale_job_ids)

            print(
                f"  {source}/{source_board}: "
                f"{len(stale_job_ids)} expired job(s) "
                f"marked inactive."
            )

        except Exception as error:
            # Lifecycle cleanup must never bring down the collector.
            print(
                f"  RECONCILE ERROR: "
                f"{source}/{source_board} - {error}"
            )

    print(
        f"Total expired jobs marked inactive: "
        f"{total_expired}"
    )

    return total_expired

def main():
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_KEY must be configured."
        )

    supabase = create_client(
        SUPABASE_URL,
        SUPABASE_KEY,
    )

    greenhouse_boards = load_greenhouse_boards()
    lever_boards = load_lever_boards()
    ashby_boards = load_ashby_boards()
    workable_boards = load_workable_boards()

    total_fetched = 0
    total_published = 0
    total_review = 0
    total_rejected = 0
    total_errors = 0

    published_jobs = []
    review_jobs = []

    # Diagnostic tracking only. These counters do not affect
    # classification, publishing, or database behavior.
    rejection_breakdown = {}
    review_breakdown = {}
    source_performance = {}
    rejection_samples = {}
    review_samples = []

    def get_source_key(job):
        company = job.get("company") or "Unknown"
        source = job.get("source") or "unknown"
        board = job.get("source_board") or "unknown"
        return f"{company} [{source}/{board}]"

    def ensure_source_stats(job):
        key = get_source_key(job)

        if key not in source_performance:
            source_performance[key] = {
                "processed": 0,
                "published": 0,
                "review": 0,
                "rejected": 0,
                "errors": 0,
            }

        return source_performance[key]

    def record_rejection(job, reason):
        rejection_breakdown[reason] = (
            rejection_breakdown.get(reason, 0) + 1
        )

        stats = ensure_source_stats(job)
        stats["rejected"] += 1

        samples = rejection_samples.setdefault(reason, [])

        if len(samples) < 5:
            samples.append({
                "title": job.get("title") or "Unknown",
                "company": job.get("company") or "Unknown",
                "location": job.get("location") or "Unknown",
            })

    def record_review(job, reason):
        review_breakdown[reason] = (
            review_breakdown.get(reason, 0) + 1
        )

        stats = ensure_source_stats(job)
        stats["review"] += 1

        review_samples.append({
            "title": job.get("title") or "Unknown",
            "company": job.get("company") or "Unknown",
            "location": job.get("location") or "Unknown",
            "reason": reason,
        })

    # Contains only boards whose ATS fetch completed successfully.
    # These are the only boards eligible for lifecycle cleanup.
    successful_boards = []

    def queue_published_job(job, reason):
        job["philippines_eligible"] = True
        job["classification_reason"] = reason
        job["category"] = classify_job(job)
        job["status"] = "active"

        published_jobs.append(
            job.copy()
        )

    def queue_review_job(
        job,
        decision,
        reason,
    ):
        review_jobs.append({
            "title": job.get("title"),
            "company": job.get("company"),
            "location": job.get("location"),
            "source": job.get("source"),
            "source_job_id": job.get(
                "source_job_id"
            ),
            "job_url": job.get("job_url"),
            "decision": decision,
            "reason": reason,
        })

    def process_job(
        job,
        raw_title="Unknown",
    ):
        nonlocal total_published
        nonlocal total_review
        nonlocal total_rejected
        nonlocal total_errors

        try:
            stats = ensure_source_stats(job)
            stats["processed"] += 1

            vacancy_decision, vacancy_reason = (
                check_active_vacancy(job)
            )

            if vacancy_decision == "reject":
                queue_review_job(
                    job,
                    "reject",
                    vacancy_reason,
                )

                record_rejection(
                    job,
                    vacancy_reason,
                )

                total_rejected += 1
                return

            relevance, relevance_reason = (
                check_va_relevance(job)
            )

            if relevance == "irrelevant":
                queue_review_job(
                    job,
                    "reject",
                    relevance_reason,
                )

                record_rejection(
                    job,
                    relevance_reason,
                )

                total_rejected += 1
                return

            decision, reason = (
                check_philippines_eligibility(
                    job
                )
            )

            if decision == "reject":
                queue_review_job(
                    job,
                    "reject",
                    reason,
                )

                record_rejection(
                    job,
                    reason,
                )

                total_rejected += 1
                return

            # ---------------------------------------------
            # LEVER WORKPLACE TYPE
            # ---------------------------------------------

            if job.get("source") == "lever":
                workplace_type = (
                    job.get(
                        "workplace_type"
                    )
                    or ""
                ).strip().lower()

                if workplace_type in {
                    "hybrid",
                    "on-site",
                    "onsite",
                }:
                    lever_reason = (
                        "Lever workplace type is "
                        f"{workplace_type}"
                    )

                    queue_review_job(
                        job,
                        "reject",
                        lever_reason,
                    )

                    record_rejection(
                        job,
                        lever_reason,
                    )

                    total_rejected += 1
                    return

            # ---------------------------------------------
            # ASHBY / GREENHOUSE REMOTE STATUS
            # ---------------------------------------------

            if job.get("source") in {
                "ashby",
                "greenhouse",
                "workable",
                "himalayas",
            }:
                (
                    remote_decision,
                    remote_reason,
                ) = check_remote_status(job)

                if remote_decision == "onsite":
                    queue_review_job(
                        job,
                        "reject",
                        remote_reason,
                    )

                    record_rejection(
                        job,
                        remote_reason,
                    )

                    total_rejected += 1
                    return

                if remote_decision == "review":
                    queue_review_job(
                        job,
                        "review",
                        remote_reason,
                    )

                    record_review(
                        job,
                        remote_reason,
                    )

                    total_review += 1
                    return

            # ---------------------------------------------
            # AMBIGUOUS ROLE / GEOGRAPHY
            # ---------------------------------------------

            if relevance == "review":
                combined_reason = (
                    f"{relevance_reason}. "
                    f"Geography: {reason}"
                )

                queue_review_job(
                    job,
                    "review",
                    combined_reason,
                )

                record_review(
                    job,
                    combined_reason,
                )

                total_review += 1
                return

            if decision == "review":
                queue_review_job(
                    job,
                    "review",
                    reason,
                )

                record_review(
                    job,
                    reason,
                )

                total_review += 1
                return

            # ---------------------------------------------
            # PUBLISH
            # ---------------------------------------------

            queue_published_job(
                job,
                reason,
            )

            stats = ensure_source_stats(job)
            stats["published"] += 1

            total_published += 1

            print(
                f"  PUBLISHED: "
                f"{job['title']} "
                f"[{job['category']}] - "
                f"{job['location']}"
            )

        except Exception as error:
            total_errors += 1

            print(
                f"  JOB ERROR: "
                f"{raw_title} - "
                f"{error}"
            )

        # =====================================================
    # GREENHOUSE
    # =====================================================

    print(
        "\n================================"
    )
    print("GREENHOUSE")
    print(
        "================================"
    )

    for board_config in greenhouse_boards:
        company = board_config["company"]
        board = board_config["board"]

        print(
            f"\nChecking "
            f"{company} ({board})..."
        )

        try:
            raw_jobs = (
                fetch_greenhouse_jobs(
                    board
                )
            )

        except Exception as error:
            print(
                f"  SOURCE FAILED: "
                f"{error}"
            )

            total_errors += 1
            continue

        print(
            f"  Found "
            f"{len(raw_jobs)} jobs."
        )

        total_fetched += len(raw_jobs)

        # ---------------------------------------------
        # COMPANY LOGO
        # ---------------------------------------------
        #
        # Fetch branding once per Greenhouse board.
        # Missing logos are completely valid and
        # simply result in company_logo_url = None.

        try:
            company_logo_url = (
                fetch_greenhouse_logo(
                    board
                )
            )

        except Exception as error:
            company_logo_url = None

            print(
                f"  LOGO LOOKUP SKIPPED: "
                f"{company} - {error}"
            )

        if company_logo_url:
            print(
                f"  LOGO FOUND: "
                f"{company}"
            )
        else:
            print(
                f"  LOGO NOT FOUND: "
                f"{company}"
            )

        # Fetch succeeded, so this board can be reconciled.
        successful_boards.append({
            "source": "greenhouse",
            "source_board": board,
            "job_ids": {
                str(raw_job.get("id"))
                for raw_job in raw_jobs
                if raw_job.get("id")
                is not None
            },
        })

        for raw_job in raw_jobs:
            try:
                job = (
                    normalize_greenhouse_job(
                        raw_job,
                        company=company,
                        board=board,
                        company_logo_url=(
                            company_logo_url
                        ),
                    )
                )

                process_job(
                    job,
                    raw_job.get(
                        "title",
                        "Unknown",
                    ),
                )

            except Exception as error:
                total_errors += 1

                print(
                    f"  JOB ERROR: "
                    f"{raw_job.get('title', 'Unknown')} "
                    f"- {error}"
                )

        # =====================================================
    # LEVER
    # =====================================================

    print(
        "\n================================"
    )
    print("LEVER")
    print(
        "================================"
    )

    for board_config in lever_boards:
        company = board_config["name"]
        slug = board_config["slug"]

        print(
            f"\nChecking "
            f"{company} ({slug})..."
        )

        try:
            raw_jobs = (
                fetch_lever_jobs(
                    slug
                )
            )

        except Exception as error:
            print(
                f"  SOURCE FAILED: "
                f"{error}"
            )

            total_errors += 1
            continue

        print(
            f"  Found "
            f"{len(raw_jobs)} jobs."
        )

        total_fetched += len(raw_jobs)

        # ---------------------------------------------
        # COMPANY LOGO
        # ---------------------------------------------
        #
        # Fetch branding once per Lever board.
        # Missing logos are completely valid and
        # simply result in company_logo_url = None.

        try:
            company_logo_url = (
                fetch_lever_company_logo(
                    slug
                )
            )

        except Exception as error:
            company_logo_url = None

            print(
                f"  LOGO LOOKUP SKIPPED: "
                f"{company} - {error}"
            )

        if company_logo_url:
            print(
                f"  LOGO FOUND: "
                f"{company}"
            )
        else:
            print(
                f"  LOGO NOT FOUND: "
                f"{company}"
            )

        successful_boards.append({
            "source": "lever",
            "source_board": slug,
            "job_ids": {
                str(raw_job.get("id"))
                for raw_job in raw_jobs
                if raw_job.get("id")
                is not None
            },
        })

        for raw_job in raw_jobs:
            try:
                job = (
                    normalize_lever_job(
                        raw_job,
                        company=company,
                        slug=slug,
                        company_logo_url=(
                            company_logo_url
                        ),
                    )
                )

                process_job(
                    job,
                    raw_job.get(
                        "text",
                        "Unknown",
                    ),
                )

            except Exception as error:
                total_errors += 1

                print(
                    f"  JOB ERROR: "
                    f"{raw_job.get('text', 'Unknown')} "
                    f"- {error}"
                )

    # =====================================================
    # ASHBY
    # =====================================================

    print(
        "\n================================"
    )
    print("ASHBY")
    print(
        "================================"
    )

    for board in ashby_boards:
        slug = board["slug"]
        company = board["name"]

        print(
            f"\nFetching Ashby jobs: "
            f"{company} ({slug})"
        )

        try:
            raw_jobs = (
                fetch_ashby_jobs(
                    slug
                )
            )

        except Exception as error:
            total_errors += 1

            print(
                f"ERROR fetching Ashby board "
                f"{company} ({slug}): "
                f"{error}"
            )

            continue

        print(
            f"Found "
            f"{len(raw_jobs)} jobs"
        )

        total_fetched += len(raw_jobs)

        # ---------------------------------------------
        # COMPANY LOGO
        # ---------------------------------------------
        #
        # Look up branding once per Ashby company,
        # not once for every individual job.
        #
        # A missing logo is completely valid and
        # simply results in company_logo_url = None.

        company_logo_url = (
            fetch_ashby_company_logo(
                slug
            )
        )

        if company_logo_url:
            print(
                f"  LOGO FOUND: "
                f"{company}"
            )
        else:
            print(
                f"  LOGO NOT FOUND: "
                f"{company}"
            )

        successful_boards.append({
            "source": "ashby",
            "source_board": slug,
            "job_ids": {
                str(raw_job.get("id"))
                for raw_job in raw_jobs
                if raw_job.get("id")
                is not None
            },
        })

        for raw_job in raw_jobs:
            try:
                job = (
                    normalize_ashby_job(
                        raw_job,
                        company,
                        slug,
                        company_logo_url=(
                            company_logo_url
                        ),
                    )
                )

                process_job(
                    job,
                    raw_title=raw_job.get(
                        "title",
                        "Unknown",
                    ),
                )

            except Exception as error:
                total_errors += 1

                print(
                    f"  JOB ERROR: "
                    f"{raw_job.get('title', 'Unknown')} "
                    f"- {error}"
                )

    # =====================================================
    # WORKABLE
    # =====================================================

    print(
        "\n================================"
    )
    print("WORKABLE")
    print(
        "================================"
    )

    for board in workable_boards:
        account = board["slug"]
        company = board["name"]

        print(
            f"\nFetching Workable jobs: "
            f"{company} ({account})"
        )

        try:
            raw_jobs = (
                fetch_workable_jobs(
                    account
                )
            )

        except Exception as error:
            total_errors += 1

            print(
                f"ERROR fetching Workable board "
                f"{company} ({account}): "
                f"{error}"
            )
            continue

        print(
            f"Found "
            f"{len(raw_jobs)} jobs"
        )

        total_fetched += len(raw_jobs)

        try:
            company_logo_url = (
                fetch_workable_company_logo(
                    account
                )
            )
        except Exception as error:
            company_logo_url = None
            print(
                f"  LOGO LOOKUP SKIPPED: "
                f"{company} - {error}"
            )

        if company_logo_url:
            print(
                f"  LOGO FOUND: "
                f"{company}"
            )
        else:
            print(
                f"  LOGO NOT FOUND: "
                f"{company}"
            )

        def workable_job_id(raw_job):
            return (
                raw_job.get("shortcode")
                or raw_job.get("id")
                or raw_job.get("code")
            )

        successful_boards.append({
            "source": "workable",
            "source_board": account,
            "job_ids": {
                str(workable_job_id(raw_job))
                for raw_job in raw_jobs
                if workable_job_id(raw_job)
                is not None
            },
        })

        for raw_job in raw_jobs:
            try:
                job = (
                    normalize_workable_job(
                        raw_job,
                        company=company,
                        account=account,
                        company_logo_url=(
                            company_logo_url
                        ),
                    )
                )

                process_job(
                    job,
                    raw_title=raw_job.get(
                        "title",
                        "Unknown",
                    ),
                )

            except Exception as error:
                total_errors += 1

                print(
                    f"  JOB ERROR: "
                    f"{raw_job.get('title', 'Unknown')} "
                    f"- {error}"
                )

    # =====================================================
    # HIMALAYAS
    # =====================================================

    print(
        "\n================================"
    )
    print("HIMALAYAS")
    print(
        "================================"
    )

    print(
        "\nFetching Himalayas jobs: "
        "Philippines + worldwide eligible"
    )

    try:
        raw_jobs, himalayas_fetch_complete = fetch_himalayas_jobs(
            country="PH",
            return_metadata=True,
        )

    except Exception as error:
        total_errors += 1
        print(
            "ERROR fetching Himalayas jobs: "
            f"{error}"
        )

    else:
        print(
            f"Found {len(raw_jobs)} jobs"
        )

        total_fetched += len(raw_jobs)

        def himalayas_job_id(raw_job):
            return raw_job.get("guid")

        if himalayas_fetch_complete:
            successful_boards.append({
                "source": "himalayas",
                "source_board": "philippines",
                "job_ids": {
                    str(himalayas_job_id(raw_job))
                    for raw_job in raw_jobs
                    if himalayas_job_id(raw_job)
                    is not None
                },
            })
        else:
            print(
                "Himalayas fetch was partial; expired-job "
                "reconciliation will be skipped for Himalayas "
                "this run."
            )

        for raw_job in raw_jobs:
            try:
                job = normalize_himalayas_job(
                    raw_job
                )

                process_job(
                    job,
                    raw_title=raw_job.get(
                        "title",
                        "Unknown",
                    ),
                )

            except Exception as error:
                total_errors += 1
                print(
                    f"  JOB ERROR: "
                    f"{raw_job.get('title', 'Unknown')} "
                    f"- {error}"
                )

    # =====================================================
    # DATABASE WRITE
    # =====================================================

    flush_job_batches(
        supabase,
        published_jobs,
        review_jobs,
    )

    # =====================================================
    # EXPIRED-JOB RECONCILIATION
    # =====================================================
    #
    # Run this only AFTER current jobs have been written.
    # Current jobs therefore remain/revert to status=active.

    total_expired = (
        reconcile_expired_jobs(
            supabase,
            successful_boards,
        )
    )

    # Count the live frontend inventory only after all writes and
    # expired-job reconciliation have completed.
    live_inventory_count, live_inventory_label = (
        get_live_inventory_count(supabase)
    )

    # =====================================================
    # SUMMARY
    # =====================================================

    print(
        "\n================================"
    )
    print("COLLECTION COMPLETE")
    print(
        "================================"
    )
    print(
        f"Fetched:   "
        f"{total_fetched}"
    )
    print(
        f"Qualified: "
        f"{total_published}"
    )
    print(
        f"Review:    "
        f"{total_review}"
    )
    print(
        f"Rejected:  "
        f"{total_rejected}"
    )
    print(
        f"Expired:   "
        f"{total_expired}"
    )
    print(
        f"Errors:    "
        f"{total_errors}"
    )
    if live_inventory_count is not None:
        print(
            f"{live_inventory_label}: "
            f"{live_inventory_count}"
        )
    else:
        print(f"{live_inventory_label}: unavailable")
    print(
        "================================"
    )

    # =====================================================
    # REJECTION BREAKDOWN
    # =====================================================

    print("\n================================")
    print("REJECTION BREAKDOWN")
    print("================================")

    for reason, count in sorted(
        rejection_breakdown.items(),
        key=lambda item: item[1],
        reverse=True,
    ):
        print(f"{count:5}  {reason}")

    print("--------------------------------")
    print(f"Total: {sum(rejection_breakdown.values())}")

    # =====================================================
    # REVIEW BREAKDOWN
    # =====================================================

    print("\n================================")
    print("REVIEW BREAKDOWN")
    print("================================")

    for reason, count in sorted(
        review_breakdown.items(),
        key=lambda item: item[1],
        reverse=True,
    ):
        print(f"{count:5}  {reason}")

    print("--------------------------------")
    print(f"Total: {sum(review_breakdown.values())}")

    # =====================================================
    # SOURCE PERFORMANCE
    # =====================================================

    print("\n================================")
    print("SOURCE PERFORMANCE")
    print("================================")

    sorted_sources = sorted(
        source_performance.items(),
        key=lambda item: item[1]["published"],
        reverse=True,
    )

    for source_name, stats in sorted_sources:
        print(f"\n{source_name}")
        print(
            f"  Processed: {stats['processed']} | "
            f"Published: {stats['published']} | "
            f"Review: {stats['review']} | "
            f"Rejected: {stats['rejected']}"
        )

    # =====================================================
    # SAMPLE REJECTIONS
    # =====================================================

    print("\n================================")
    print("SAMPLE REJECTIONS")
    print("================================")

    top_rejection_samples = sorted(
        rejection_samples.items(),
        key=lambda item: rejection_breakdown.get(
            item[0],
            0,
        ),
        reverse=True,
    )[:15]

    for reason, samples in top_rejection_samples:
        print(
            f"\n{reason} "
            f"({rejection_breakdown.get(reason, 0)})"
        )

        for sample in samples:
            print(
                f"  - {sample['title']} | "
                f"{sample['company']} | "
                f"{sample['location']}"
            )


    # =====================================================
    # SAMPLE REVIEW JOBS
    # =====================================================

    print("\n================================")
    print("SAMPLE REVIEW JOBS")
    print("================================")

    if not review_samples:
        print("No jobs sent to review.")
    else:
        for index, sample in enumerate(
            review_samples,
            start=1,
        ):
            print(
                f"{index:3}. "
                f"{sample['title']} | "
                f"{sample['company']} | "
                f"{sample['location']} | "
                f"{sample['reason']}"
            )

    print("--------------------------------")
    print(f"Total review jobs: {len(review_samples)}")

    # =====================================================
    # FINAL SUMMARY
    # =====================================================
    # Keep this as the final log block so GitHub Actions always
    # shows the key collection numbers after verbose diagnostics.

    print("\n================================")
    print("FINAL SUMMARY")
    print("================================")
    print(f"Fetched:   {total_fetched}")
    print(f"Qualified: {total_published}")
    print(f"Review:    {total_review}")
    print(f"Rejected:  {total_rejected}")
    print(f"Expired:   {total_expired}")
    print(f"Errors:    {total_errors}")
    if live_inventory_count is not None:
        print(f"{live_inventory_label}: {live_inventory_count}")
    else:
        print(f"{live_inventory_label}: unavailable")
    print("================================")


if __name__ == "__main__":
    main()
