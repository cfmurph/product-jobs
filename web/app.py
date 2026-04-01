"""Flask web application for product-jobs."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(override=False)  # load .env but don't override vars already in the environment

from flask import Flask, redirect, render_template, request, url_for, flash
from werkzeug.utils import secure_filename

from src.tracker.jobs import (
    get_jobs, update_job_status, add_note, delete_job,
    add_resume, get_active_resume, reclassify_all_jobs, VALID_STATUSES,
)
from src.tracker.stats import (
    get_funnel_stats, get_stats_by_site, get_stats_by_level,
    get_top_missing_skills, get_score_distribution,
)
from src.resume.gap import analyse_gap_from_job
from src.classifier.skills import skills_from_db
from src.scrapers.jobspy_scraper import search_jobs, search_product_jobs, SUPPORTED_SITES
from src.agent import claude as agent

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.urandom(24)


@app.template_filter("count_json_items")
def count_json_items(s):
    """Return the length of a JSON-encoded list, or 0 on failure."""
    try:
        return len(json.loads(s)) if s else 0
    except Exception:
        return 0

UPLOAD_ALLOWED = {".pdf", ".docx", ".doc", ".txt"}


def _salary_str(job) -> str:
    if job.salary_min or job.salary_max:
        lo = f"${job.salary_min:,.0f}" if job.salary_min else "?"
        hi = f"${job.salary_max:,.0f}" if job.salary_max else "?"
        interval = f"/{job.salary_interval[0]}" if job.salary_interval else ""
        return f"{lo}–{hi}{interval}"
    return ""


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.route("/")
def dashboard():
    funnel = get_funnel_stats()
    by_site = get_stats_by_site()
    by_level = get_stats_by_level()
    top_gaps = get_top_missing_skills(limit=10)
    score_dist = get_score_distribution()
    resume = get_active_resume()
    recent_jobs = get_jobs(limit=8)
    return render_template(
        "dashboard.html",
        funnel=funnel,
        by_site=by_site,
        by_level=by_level,
        top_gaps=top_gaps,
        score_dist=score_dist,
        resume=resume,
        recent_jobs=recent_jobs,
        salary_str=_salary_str,
    )


# ---------------------------------------------------------------------------
# Job list
# ---------------------------------------------------------------------------

@app.route("/jobs")
def job_list():
    status = request.args.get("status") or None
    site = request.args.get("site") or None
    level = request.args.get("level") or None
    remote = request.args.get("remote") == "1"
    min_score_raw = request.args.get("min_score") or None
    min_score = float(min_score_raw) if min_score_raw else None
    search = request.args.get("q") or None
    page = max(int(request.args.get("page", 1)), 1)
    per_page = 40
    offset = (page - 1) * per_page

    jobs = get_jobs(
        status=status,
        site=site,
        remote_only=remote,
        min_score=min_score,
        search=search,
        limit=per_page + 1,
        offset=offset,
    )

    # Manual level filter (not in DB query layer yet — small dataset so fine)
    if level:
        jobs = [j for j in jobs if j.level == level]

    has_next = len(jobs) > per_page
    jobs = jobs[:per_page]

    resume = get_active_resume()
    return render_template(
        "jobs.html",
        jobs=jobs,
        status=status,
        site=site,
        level=level,
        remote=remote,
        min_score=min_score_raw or "",
        search=search or "",
        page=page,
        has_next=has_next,
        valid_statuses=sorted(VALID_STATUSES),
        supported_sites=SUPPORTED_SITES,
        salary_str=_salary_str,
        resume=resume,
    )


# ---------------------------------------------------------------------------
# Job detail
# ---------------------------------------------------------------------------

@app.route("/jobs/<int:job_id>")
def job_detail(job_id):
    all_jobs = get_jobs(limit=10000)
    job = next((j for j in all_jobs if j.id == job_id), None)
    if not job:
        flash("Job not found.", "error")
        return redirect(url_for("job_list"))

    skills = skills_from_db(job.required_skills, job.preferred_skills, job.skill_categories)

    resume = get_active_resume()
    gap = None
    if resume and resume.keywords:
        resume_keywords = [k.strip() for k in resume.keywords.split(",") if k.strip()]
        gap = analyse_gap_from_job(job, resume_keywords)

    return render_template(
        "job_detail.html",
        job=job,
        skills=skills,
        gap=gap,
        salary_str=_salary_str,
        valid_statuses=sorted(VALID_STATUSES),
        resume=resume,
    )


@app.route("/jobs/<int:job_id>/status", methods=["POST"])
def update_status(job_id):
    new_status = request.form.get("status")
    note = request.form.get("note", "").strip() or None
    if new_status:
        update_job_status(str(job_id), new_status, notes=note)
        flash(f"Status updated to '{new_status}'.", "success")
    return redirect(url_for("job_detail", job_id=job_id))


@app.route("/jobs/<int:job_id>/note", methods=["POST"])
def post_note(job_id):
    note = request.form.get("note", "").strip()
    if note:
        add_note(str(job_id), note)
        flash("Note added.", "success")
    return redirect(url_for("job_detail", job_id=job_id))


@app.route("/jobs/<int:job_id>/delete", methods=["POST"])
def remove_job(job_id):
    delete_job(str(job_id))
    flash("Job deleted.", "success")
    return redirect(url_for("job_list"))


# ---------------------------------------------------------------------------
# Search (trigger from web)
# ---------------------------------------------------------------------------

@app.route("/search", methods=["GET", "POST"])
def search_page():
    results = []
    inserted = skipped = 0
    searched = False

    if request.method == "POST":
        term = request.form.get("term", "").strip()
        location = request.form.get("location", "United States").strip()
        sites_raw = request.form.getlist("sites")
        remote = request.form.get("remote") == "1"
        results_n = int(request.form.get("results", 25))
        hours_old = int(request.form.get("hours_old", 168))
        save_results = request.form.get("save") == "1"

        sites = sites_raw if sites_raw else None

        try:
            if term:
                raw = search_jobs(
                    search_term=term,
                    location=location,
                    sites=sites,
                    results_wanted=results_n,
                    hours_old=hours_old,
                    remote_only=remote,
                )
            else:
                raw = search_product_jobs(
                    location=location,
                    sites=sites,
                    results_per_term=results_n,
                    hours_old=hours_old,
                    remote_only=remote,
                )

            if save_results and raw:
                from src.tracker.jobs import upsert_jobs
                inserted, skipped = upsert_jobs(raw)

            results = raw
            searched = True
            flash(f"Found {len(raw)} jobs. Saved {inserted} new.", "success")
        except Exception as exc:
            flash(f"Search error: {exc}", "error")

    return render_template(
        "search.html",
        results=results,
        inserted=inserted,
        skipped=skipped,
        searched=searched,
        supported_sites=SUPPORTED_SITES,
    )


# ---------------------------------------------------------------------------
# Resume
# ---------------------------------------------------------------------------

@app.route("/resume", methods=["GET", "POST"])
def resume_page():
    resume = get_active_resume()

    if request.method == "POST":
        f = request.files.get("resume_file")
        if not f or not f.filename:
            flash("No file selected.", "error")
            return redirect(url_for("resume_page"))
        ext = Path(f.filename).suffix.lower()
        if ext not in UPLOAD_ALLOWED:
            flash(f"Unsupported file type '{ext}'. Use PDF, DOCX, or TXT.", "error")
            return redirect(url_for("resume_page"))

        tmp = Path("data/resumes") / secure_filename(f.filename)
        tmp.parent.mkdir(parents=True, exist_ok=True)
        f.save(tmp)

        try:
            resume = add_resume(str(tmp))
            flash(f"Resume '{resume.filename}' uploaded and all jobs re-scored.", "success")
        except Exception as exc:
            flash(f"Error processing resume: {exc}", "error")

        return redirect(url_for("resume_page"))

    kw_list = []
    if resume and resume.keywords:
        kw_list = [k.strip() for k in resume.keywords.split(",") if k.strip()]

    return render_template("resume.html", resume=resume, kw_list=kw_list)


@app.route("/reclassify", methods=["POST"])
def reclassify():
    count = reclassify_all_jobs()
    flash(f"Reclassified {count} jobs.", "success")
    return redirect(url_for("dashboard"))


# ---------------------------------------------------------------------------
# AI agent routes
# ---------------------------------------------------------------------------

@app.route("/suggest")
def suggest_page():
    """Portfolio-level resume improvement suggestions."""
    resume = get_active_resume()
    ai_available = agent.is_available()

    suggestions = None
    if ai_available and resume and resume.raw_text:
        top_gaps = get_top_missing_skills(limit=15)
        if top_gaps:
            target = int(request.args.get("target", 80))
            suggestions = agent.aggregate_resume_suggestions(
                resume_text=resume.raw_text,
                top_missing_skills=top_gaps,
                target_coverage=target,
            )

    top_gaps = get_top_missing_skills(limit=15)
    return render_template(
        "suggest.html",
        resume=resume,
        ai_available=ai_available,
        suggestions=suggestions,
        top_gaps=top_gaps,
        target=int(request.args.get("target", 80)),
    )


@app.route("/jobs/<int:job_id>/suggest")
def job_suggest(job_id):
    """Per-job AI resume suggestions + application advice."""
    all_jobs = get_jobs(limit=10000)
    job = next((j for j in all_jobs if j.id == job_id), None)
    if not job:
        flash("Job not found.", "error")
        return redirect(url_for("job_list"))

    resume = get_active_resume()
    ai_available = agent.is_available()
    target = int(request.args.get("target", 80))

    suggestions = None
    advice = None
    semantic = None
    gap = None

    if resume and resume.keywords:
        resume_keywords = [k.strip() for k in resume.keywords.split(",") if k.strip()]
        gap = analyse_gap_from_job(job, resume_keywords)

    if ai_available and resume and resume.raw_text:
        if gap and gap["coverage_score"] < target:
            suggestions = agent.suggest_resume_edits(
                resume_text=resume.raw_text,
                job_title=job.title,
                job_description=job.description or "",
                missing_skills=gap["missing"] if gap else [],
                have_skills=gap["have"] if gap else [],
                target_coverage=target,
            )

        advice = agent.job_application_advice(
            resume_text=resume.raw_text,
            job_title=job.title,
            job_description=job.description or "",
            company=job.company or "",
        )

        semantic = agent.semantic_match_score(
            resume_text=resume.raw_text,
            job_description=job.description or "",
            job_title=job.title,
        )

    return render_template(
        "job_suggest.html",
        job=job,
        resume=resume,
        ai_available=ai_available,
        suggestions=suggestions,
        advice=advice,
        semantic=semantic,
        gap=gap,
        target=target,
        salary_str=_salary_str,
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)
