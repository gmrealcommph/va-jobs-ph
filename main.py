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

        # Preserve line breaks before stripping HTML.
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

        # Preserve list items.
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

        # Remove remaining HTML tags.
        text = re.sub(
            r"<[^>]+>",
            "",
            text,
        )

        text = html.unescape(text)

        # Normalise non-breaking spaces.
        text = text.replace(
            "\xa0",
            " ",
        )

        # Remove unnecessary whitespace around lines.
        lines = [
            line.strip()
            for line in text.splitlines()
        ]

        # Collapse excessive blank lines.
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
    # 4. Additional information
    # -------------------------------------------------

    additional_plain = (
        raw_job.get("additionalPlain")
        or ""
    ).strip()

    if additional_plain:
        description_parts.append(
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
            description_parts.append(
                additional_text
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
    # 3. LOCATION EXPLICITLY INDICATES REMOTE WORK
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
    # 4. DESCRIPTION EXPLICITLY CONFIRMS REMOTE WORK
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
    # 5. EXPLICIT NON-REMOTE FLAG
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
    # 6. REMOTE STATUS UNKNOWN
    # ---------------------------------------------------------

    return (
        "review",
        "Remote status is not specified",
    )


def check_philippines_eligibility(job):
    """
    Return:
      publish = clear evidence Philippines applicants are eligible
      review  = potentially eligible, but location is ambiguous
      reject  = no evidence Philippines applicants are eligible
    """

    location = clean_text(job.get("location")).lower().strip()

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

    if any(term in location for term in philippines_terms):
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

    if any(term in location for term in apac_terms):
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

    if any(term in location for term in worldwide_terms):
        return (
            "publish",
            "Location explicitly allows worldwide applicants",
        )

    generic_remote = [
        "remote",
        "fully remote",
        "remote - remote",
    ]

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
        "office coordinator",
        "office assistant",
        "remote assistant",

        # Customer service / support
        "customer support",
        "customer service",
        "customer experience",
        "customer care",
        "support specialist",
        "support representative",
        "support agent",
        "customer service representative",

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
        "seo specialist",
        "seo assistant",

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

        # Bookkeeping / finance support
        "bookkeeper",
        "bookkeeping",
        "accounting assistant",
        "accounts payable",
        "accounts receivable",
        "billing specialist",
        "payroll specialist",

        # Recruitment / HR
        "recruiter",
        "recruitment coordinator",
        "talent acquisition coordinator",
        "hr assistant",
        "hr coordinator",
        "hr specialist",
        "hr generalist",
        "human resources assistant",

        # Writing / content
        "copywriter",
        "content writer",
        "content editor",
        "blog writer",

        # Design / creative
        "graphic designer",
        "video editor",
        "motion designer",

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
    # 7. EVERYTHING ELSE
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
            ],
        ),
        (
            "Customer Support",
            [
                "customer support",
                "customer service",
                "support specialist",
                "support representative",
                "customer success",
                "customer experience",
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
                "seo",
                "email marketer",
            ],
        ),
        (
            "E-commerce",
            [
                "ecommerce",
                "e-commerce",
                "shopify",
                "amazon specialist",
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
            ],
        ),
        (
            "Recruitment & HR",
            [
                "recruiter",
                "recruitment",
                "talent acquisition",
                "human resources",
                "hr specialist",
                "hr coordinator",
                "people operations",
                "hr assistant",
                "hr generalist",
            ],
        ),
        (
            "Design & Creative",
            [
                "graphic designer",
                "designer",
                "video editor",
                "motion designer",
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

    print("\n================================")
    print("WRITING DATABASE BATCHES")
    print("================================")

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

    total_fetched = 0
    total_published = 0
    total_review = 0
    total_rejected = 0
    total_errors = 0

    published_jobs = []
    review_jobs = []

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
            vacancy_decision, vacancy_reason = (
                check_active_vacancy(job)
            )

            if vacancy_decision == "reject":
                queue_review_job(
                    job,
                    "reject",
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
                    queue_review_job(
                        job,
                        "reject",
                        (
                            "Lever workplace type is "
                            f"{workplace_type}"
                        ),
                    )

                    total_rejected += 1
                    return

            # ---------------------------------------------
            # ASHBY / GREENHOUSE REMOTE STATUS
            # ---------------------------------------------

            if job.get("source") in {
                "ashby",
                "greenhouse",
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

                    total_rejected += 1
                    return

                if remote_decision == "review":
                    queue_review_job(
                        job,
                        "review",
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

                total_review += 1
                return

            if decision == "review":
                queue_review_job(
                    job,
                    "review",
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
        f"Published: "
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
    print(
        "================================"
    )


if __name__ == "__main__":
    main()
