"""Application tracker — persist, query, and update jobs in the SQLite database."""
import csv
import datetime
import json
import os
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from src.db.models import Job, Resume, get_engine, get_session, init_db
from src.resume.parser import (
    extract_keywords,
    extract_text,
    save_resume_file,
    score_job_against_resume,
)
from src.classifier.level import classify_level
from src.classifier.skills import extract_skills, skills_to_json
from src.resume.gap import analyse_gap

VALID_STATUSES = {"saved", "applied", "interviewing", "offer", "rejected", "archived"}


def _get_db_path() -> str:
    path = os.getenv("DB_PATH", "data/jobs.db")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return path


def _session() -> tuple[Session, object]:
    db_path = _get_db_path()
    engine = init_db(db_path)
    return get_session(engine), engine


# ---------------------------------------------------------------------------
# Job persistence
# ---------------------------------------------------------------------------

def upsert_jobs(jobs: list[dict], session: Optional[Session] = None) -> tuple[int, int]:
    """
    Insert new jobs, skip duplicates (by job_id).
    Returns (inserted_count, skipped_count).
    """
    close = session is None
    if session is None:
        session, _ = _session()

    inserted = 0
    skipped = 0

    try:
        active_resume = _active_resume(session)
        resume_keywords = []
        if active_resume and active_resume.keywords:
            resume_keywords = [k.strip() for k in active_resume.keywords.split(",") if k.strip()]

        for data in jobs:
            existing = session.query(Job).filter_by(job_id=data["job_id"]).first()
            if existing:
                skipped += 1
                continue

            job = Job(**{k: v for k, v in data.items() if hasattr(Job, k)})

            # Classify level and extract skills
            job.level = classify_level(job.title, job.description)
            skills = extract_skills(job.description)
            job.required_skills, job.preferred_skills, job.skill_categories = skills_to_json(skills)

            # Score against active resume + gap analysis
            if resume_keywords and job.description:
                score, matched = score_job_against_resume(job.description, resume_keywords)
                job.match_score = score
                job.matched_keywords = ", ".join(matched)
                gap = analyse_gap(skills["required_skills"], skills["preferred_skills"], resume_keywords)
                job.gap_skills = ", ".join(gap["missing"])

            session.add(job)
            inserted += 1

        session.commit()
    finally:
        if close:
            session.close()

    return inserted, skipped


def get_jobs(
    status: Optional[str] = None,
    site: Optional[str] = None,
    remote_only: bool = False,
    min_score: Optional[float] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    session: Optional[Session] = None,
) -> list[Job]:
    close = session is None
    if session is None:
        session, _ = _session()

    try:
        q = session.query(Job)
        if status:
            q = q.filter(Job.status == status)
        if site:
            q = q.filter(Job.site == site)
        if remote_only:
            q = q.filter(Job.is_remote == True)
        if min_score is not None:
            q = q.filter(Job.match_score >= min_score)
        if search:
            term = f"%{search.lower()}%"
            q = q.filter(
                (Job.title.ilike(term)) |
                (Job.company.ilike(term)) |
                (Job.description.ilike(term))
            )
        q = q.order_by(Job.scraped_at.desc()).offset(offset).limit(limit)
        jobs = q.all()
        # Detach from session so caller can use after close
        session.expunge_all()
        return jobs
    finally:
        if close:
            session.close()


def update_job_status(job_id_or_pk: str, status: str, notes: Optional[str] = None) -> bool:
    """Update a job's application status. Returns True if found and updated."""
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status '{status}'. Choose from: {', '.join(sorted(VALID_STATUSES))}")

    session, _ = _session()
    try:
        job = (
            session.query(Job).filter_by(id=int(job_id_or_pk)).first()
            if job_id_or_pk.isdigit()
            else session.query(Job).filter_by(job_id=job_id_or_pk).first()
        )
        if not job:
            return False
        job.status = status
        if notes is not None:
            job.notes = notes
        now = datetime.datetime.utcnow()
        if status == "applied":
            job.applied_at = now
        if status in ("interviewing", "offer", "rejected") and not job.responded_at:
            job.responded_at = now
        session.commit()
        return True
    finally:
        session.close()


def add_note(job_id_or_pk: str, note: str) -> bool:
    session, _ = _session()
    try:
        job = (
            session.query(Job).filter_by(id=int(job_id_or_pk)).first()
            if job_id_or_pk.isdigit()
            else session.query(Job).filter_by(job_id=job_id_or_pk).first()
        )
        if not job:
            return False
        existing = job.notes or ""
        timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M")
        job.notes = f"{existing}\n[{timestamp}] {note}".strip()
        session.commit()
        return True
    finally:
        session.close()


def delete_job(job_id_or_pk: str) -> bool:
    session, _ = _session()
    try:
        job = (
            session.query(Job).filter_by(id=int(job_id_or_pk)).first()
            if job_id_or_pk.isdigit()
            else session.query(Job).filter_by(job_id=job_id_or_pk).first()
        )
        if not job:
            return False
        session.delete(job)
        session.commit()
        return True
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Resume management
# ---------------------------------------------------------------------------

def _active_resume(session: Session) -> Optional[Resume]:
    return session.query(Resume).filter_by(is_active=True).order_by(Resume.uploaded_at.desc()).first()


def add_resume(filepath: str) -> Resume:
    """Parse a resume file, store it, and re-score all saved jobs."""
    dest = save_resume_file(filepath)
    text = extract_text(dest)
    keywords = extract_keywords(text)

    session, _ = _session()
    try:
        # Deactivate existing resumes
        session.query(Resume).update({"is_active": False})

        resume = Resume(
            filename=Path(dest).name,
            filepath=dest,
            raw_text=text,
            keywords=", ".join(keywords),
            is_active=True,
        )
        session.add(resume)
        session.commit()

        # Re-score all jobs
        _rescore_all_jobs(session, keywords)
        session.commit()
        session.expunge(resume)
        return resume
    finally:
        session.close()


def _rescore_all_jobs(session: Session, resume_keywords: list[str]) -> None:
    from src.classifier.skills import skills_from_db
    for job in session.query(Job).all():
        if job.description:
            score, matched = score_job_against_resume(job.description, resume_keywords)
            job.match_score = score
            job.matched_keywords = ", ".join(matched)
            # Refresh gap analysis against updated resume
            skills = skills_from_db(job.required_skills, job.preferred_skills, job.skill_categories)
            gap = analyse_gap(skills["required_skills"], skills["preferred_skills"], resume_keywords)
            job.gap_skills = ", ".join(gap["missing"])


def get_active_resume() -> Optional[Resume]:
    session, _ = _session()
    try:
        r = _active_resume(session)
        if r:
            session.expunge(r)
        return r
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_to_csv(
    filepath: str = "exports/jobs.csv",
    status: Optional[str] = None,
    min_score: Optional[float] = None,
) -> int:
    """Export jobs to CSV. Returns row count written."""
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    jobs = get_jobs(status=status, min_score=min_score, limit=10000)

    if not jobs:
        return 0

    fields = [
        "id", "title", "company", "location", "site", "job_type", "is_remote",
        "salary_min", "salary_max", "salary_interval", "match_score",
        "matched_keywords", "status", "job_url", "date_posted", "scraped_at", "notes",
    ]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for job in jobs:
            writer.writerow({k: getattr(job, k, "") for k in fields})

    return len(jobs)


def export_to_json(
    filepath: str = "exports/jobs.json",
    status: Optional[str] = None,
    min_score: Optional[float] = None,
) -> int:
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    jobs = get_jobs(status=status, min_score=min_score, limit=10000)

    if not jobs:
        return 0

    records = []
    for job in jobs:
        records.append({
            "id": job.id,
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "site": job.site,
            "job_type": job.job_type,
            "is_remote": job.is_remote,
            "salary_min": job.salary_min,
            "salary_max": job.salary_max,
            "salary_interval": job.salary_interval,
            "match_score": job.match_score,
            "matched_keywords": job.matched_keywords,
            "status": job.status,
            "job_url": job.job_url,
            "date_posted": str(job.date_posted) if job.date_posted else None,
            "scraped_at": str(job.scraped_at) if job.scraped_at else None,
            "notes": job.notes,
        })

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, default=str)

    return len(records)


# ---------------------------------------------------------------------------
# Reclassify existing jobs
# ---------------------------------------------------------------------------

def reclassify_all_jobs() -> int:
    """
    Run level classifier + skill extractor + gap analysis on every job in the DB.
    Useful after upgrading classifier logic or loading a new resume.
    Returns number of jobs updated.
    """
    from src.classifier.skills import skills_from_db
    session, _ = _session()
    try:
        active_resume = _active_resume(session)
        resume_keywords = []
        if active_resume and active_resume.keywords:
            resume_keywords = [k.strip() for k in active_resume.keywords.split(",") if k.strip()]

        count = 0
        for job in session.query(Job).all():
            job.level = classify_level(job.title, job.description)
            skills = extract_skills(job.description)
            job.required_skills, job.preferred_skills, job.skill_categories = skills_to_json(skills)

            if resume_keywords and job.description:
                score, matched = score_job_against_resume(job.description, resume_keywords)
                job.match_score = score
                job.matched_keywords = ", ".join(matched)
                gap = analyse_gap(skills["required_skills"], skills["preferred_skills"], resume_keywords)
                job.gap_skills = ", ".join(gap["missing"])

            count += 1

        session.commit()
        return count
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def get_stats() -> dict:
    session, _ = _session()
    try:
        total = session.query(Job).count()
        by_status: dict = {}
        for s in VALID_STATUSES:
            by_status[s] = session.query(Job).filter_by(status=s).count()
        by_site: dict = {}
        for site in ["linkedin", "indeed", "glassdoor", "zip_recruiter"]:
            by_site[site] = session.query(Job).filter_by(site=site).count()
        remote = session.query(Job).filter_by(is_remote=True).count()
        return {
            "total": total,
            "by_status": by_status,
            "by_site": by_site,
            "remote": remote,
        }
    finally:
        session.close()
