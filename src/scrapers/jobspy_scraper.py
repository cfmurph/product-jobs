"""Job scraper powered by python-jobspy.

Supports LinkedIn, Indeed, Glassdoor, and ZipRecruiter.
LinkedIn authenticated scraping is enabled when LINKEDIN_EMAIL / LINKEDIN_PASSWORD
are present in the environment (via .env).
"""
import datetime
import hashlib
import os
from typing import Optional

from dotenv import load_dotenv
from jobspy import scrape_jobs

load_dotenv()

# Sites supported by jobspy
SUPPORTED_SITES = ["linkedin", "indeed", "glassdoor", "zip_recruiter"]

# Product-focused search terms (defaults)
DEFAULT_PRODUCT_TERMS = [
    "product manager",
    "senior product manager",
    "principal product manager",
    "director of product",
    "VP of product",
    "head of product",
    "group product manager",
    "product lead",
]


def _make_job_id(site: str, url: str, title: str, company: str) -> str:
    """Deterministic ID so re-scraping does not create duplicates."""
    raw = f"{site}:{url or ''}:{title}:{company}"
    return hashlib.md5(raw.encode()).hexdigest()


def _to_datetime(val) -> Optional[datetime.datetime]:
    if val is None:
        return None
    if isinstance(val, datetime.datetime):
        return val
    if isinstance(val, datetime.date):
        return datetime.datetime(val.year, val.month, val.day)
    try:
        return datetime.datetime.fromisoformat(str(val))
    except Exception:
        return None


def _safe_float(val) -> Optional[float]:
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def search_jobs(
    search_term: str,
    location: str = "United States",
    sites: list[str] | None = None,
    results_wanted: int = 50,
    hours_old: int = 168,  # 1 week default
    remote_only: bool = False,
    country_indeed: str = "usa",
    linkedin_fetch_description: bool = True,
) -> list[dict]:
    """
    Search for jobs across multiple job boards.

    Returns a list of dicts with normalized job data ready to be persisted.
    """
    if sites is None:
        sites = SUPPORTED_SITES

    linkedin_email = os.getenv("LINKEDIN_EMAIL")
    linkedin_password = os.getenv("LINKEDIN_PASSWORD")
    proxy = os.getenv("PROXY")

    kwargs = dict(
        site_name=sites,
        search_term=search_term,
        location=location,
        results_wanted=results_wanted,
        hours_old=hours_old,
        country_indeed=country_indeed,
        linkedin_fetch_description=linkedin_fetch_description,
    )

    if linkedin_email and linkedin_password:
        kwargs["linkedin_email"] = linkedin_email
        kwargs["linkedin_password"] = linkedin_password

    if proxy:
        kwargs["proxies"] = [proxy]

    try:
        df = scrape_jobs(**kwargs)
    except Exception as exc:
        raise RuntimeError(f"Scrape failed: {exc}") from exc

    if df is None or df.empty:
        return []

    jobs = []
    for _, row in df.iterrows():
        site = str(row.get("site", "unknown")).lower()
        title = str(row.get("title", "")).strip()
        company = str(row.get("company", "")).strip()
        url = str(row.get("job_url", "")).strip()

        job = {
            "job_id": _make_job_id(site, url, title, company),
            "site": site,
            "title": title,
            "company": company,
            "location": str(row.get("location", "")).strip(),
            "job_type": str(row.get("job_type", "")).strip() or None,
            "is_remote": bool(row.get("is_remote", False)),
            "salary_min": _safe_float(row.get("min_amount")),
            "salary_max": _safe_float(row.get("max_amount")),
            "salary_currency": str(row.get("currency", "USD") or "USD"),
            "salary_interval": str(row.get("interval", "") or "").strip() or None,
            "description": str(row.get("description", "") or "").strip() or None,
            "job_url": url or None,
            "date_posted": _to_datetime(row.get("date_posted")),
        }
        jobs.append(job)

    return jobs


def search_product_jobs(
    location: str = "United States",
    sites: list[str] | None = None,
    results_per_term: int = 25,
    hours_old: int = 168,
    remote_only: bool = False,
    extra_terms: list[str] | None = None,
) -> list[dict]:
    """
    Run searches across all default product management titles.
    Deduplicates by job_id before returning.
    """
    terms = list(DEFAULT_PRODUCT_TERMS)
    if extra_terms:
        terms.extend(extra_terms)

    seen: set[str] = set()
    all_jobs: list[dict] = []

    for term in terms:
        try:
            results = search_jobs(
                search_term=term,
                location=location,
                sites=sites,
                results_wanted=results_per_term,
                hours_old=hours_old,
                remote_only=remote_only,
            )
            for job in results:
                if job["job_id"] not in seen:
                    seen.add(job["job_id"])
                    all_jobs.append(job)
        except RuntimeError as exc:
            # Surface errors without aborting the whole run
            print(f"[warn] term='{term}': {exc}")

    return all_jobs
