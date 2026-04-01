#!/usr/bin/env python3
"""
product-jobs — CLI for finding and tracking product management jobs.

Usage examples:
  python main.py search --help
  python main.py search --term "senior product manager" --location "San Francisco, CA"
  python main.py search --remote --sites linkedin indeed
  python main.py list
  python main.py list --status saved --min-score 30
  python main.py status 42 applied
  python main.py note 42 "Strong fintech background, reached out to recruiter"
  python main.py resume add /path/to/resume.pdf
  python main.py resume show
  python main.py export --format csv
  python main.py stats
"""
import sys
from pathlib import Path

# Make src importable when running from repo root
sys.path.insert(0, str(Path(__file__).parent))

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich import box

load_dotenv(override=False)  # load .env but don't override vars already in the environment

from src.scrapers.jobspy_scraper import search_jobs, search_product_jobs, SUPPORTED_SITES
from src.tracker.jobs import (
    upsert_jobs, get_jobs, update_job_status, add_note, delete_job,
    add_resume, get_active_resume, export_to_csv, export_to_json,
    get_stats, reclassify_all_jobs, VALID_STATUSES,
)
from src.tracker.stats import (
    get_funnel_stats, get_stats_by_site, get_stats_by_level,
    get_top_missing_skills, get_score_distribution,
)
from src.resume.gap import analyse_gap_from_job
from src.classifier.skills import skills_from_db
from src.agent import claude as agent

console = Console()

STATUS_COLORS = {
    "saved": "cyan",
    "applied": "blue",
    "interviewing": "yellow",
    "offer": "green",
    "rejected": "red",
    "archived": "dim",
}


def _salary_str(job) -> str:
    if job.salary_min or job.salary_max:
        lo = f"${job.salary_min:,.0f}" if job.salary_min else "?"
        hi = f"${job.salary_max:,.0f}" if job.salary_max else "?"
        interval = f"/{job.salary_interval[0]}" if job.salary_interval else ""
        return f"{lo}–{hi}{interval}"
    return ""


def _print_jobs_table(jobs, title: str = "Jobs") -> None:
    if not jobs:
        console.print("[yellow]No jobs found.[/yellow]")
        return

    table = Table(
        title=title,
        box=box.ROUNDED,
        show_lines=False,
        highlight=True,
    )
    table.add_column("#", style="dim", width=5, no_wrap=True)
    table.add_column("Title", min_width=26, max_width=38)
    table.add_column("Company", min_width=14, max_width=22)
    table.add_column("Location", min_width=12, max_width=20)
    table.add_column("Level", width=12)
    table.add_column("Site", width=10)
    table.add_column("Salary", width=14)
    table.add_column("Score", width=6)
    table.add_column("Gap%", width=6)
    table.add_column("Status", width=12)
    table.add_column("Rem", width=4)

    for job in jobs:
        score = f"{job.match_score:.0f}%" if job.match_score is not None else ""
        gap_pct = ""
        if job.gap_skills is not None and job.required_skills:
            import json as _json
            try:
                req = _json.loads(job.required_skills)
                n_missing = len([s for s in job.gap_skills.split(",") if s.strip()])
                gap_pct = f"{round(n_missing/max(len(req),1)*100):.0f}%" if req else ""
            except Exception:
                pass
        color = STATUS_COLORS.get(job.status or "saved", "white")
        remote = "[green]✓[/green]" if job.is_remote else ""
        table.add_row(
            str(job.id),
            job.title or "",
            job.company or "",
            job.location or "",
            job.level or "",
            job.site or "",
            _salary_str(job),
            score,
            gap_pct,
            f"[{color}]{job.status or 'saved'}[/{color}]",
            remote,
        )

    console.print(table)
    console.print(f"  [dim]{len(jobs)} job(s)[/dim]")


# ---------------------------------------------------------------------------
# CLI root
# ---------------------------------------------------------------------------

@click.group()
def cli():
    """product-jobs: search, track, and score product management jobs."""


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--term", "-t", multiple=True,
              help="Search term(s). Defaults to a curated list of PM titles.")
@click.option("--location", "-l", default="United States",
              show_default=True, help="Location filter.")
@click.option("--sites", "-s", multiple=True,
              type=click.Choice(SUPPORTED_SITES, case_sensitive=False),
              help="Job boards to search (default: all).")
@click.option("--results", "-n", default=25, show_default=True,
              help="Results per search term.")
@click.option("--hours-old", default=168, show_default=True,
              help="Only jobs posted within this many hours.")
@click.option("--remote", is_flag=True, default=False,
              help="Filter to remote jobs only.")
@click.option("--no-save", is_flag=True, default=False,
              help="Print results without saving to database.")
def search(term, location, sites, results, hours_old, remote, no_save):
    """Search job boards for product management roles."""
    sites_list = list(sites) if sites else None

    with console.status("[bold green]Searching job boards…[/bold green]"):
        if term:
            all_jobs = []
            seen: set[str] = set()
            for t in term:
                found = search_jobs(
                    search_term=t,
                    location=location,
                    sites=sites_list,
                    results_wanted=results,
                    hours_old=hours_old,
                    remote_only=remote,
                )
                for j in found:
                    if j["job_id"] not in seen:
                        seen.add(j["job_id"])
                        all_jobs.append(j)
        else:
            all_jobs = search_product_jobs(
                location=location,
                sites=sites_list,
                results_per_term=results,
                hours_old=hours_old,
                remote_only=remote,
            )

    console.print(f"[green]Found {len(all_jobs)} unique job(s).[/green]")

    if not no_save and all_jobs:
        inserted, skipped = upsert_jobs(all_jobs)
        console.print(f"  [dim]Saved: {inserted} new | Skipped (dup): {skipped}[/dim]")

    # Show a preview table of what was found
    if all_jobs:
        from src.db.models import Job
        preview = []
        for d in all_jobs[:30]:
            j = Job(**{k: v for k, v in d.items() if hasattr(Job, k)})
            preview.append(j)
        _print_jobs_table(preview, title=f"Search Results (first {len(preview)})")


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

@cli.command(name="list")
@click.option("--status", type=click.Choice(list(VALID_STATUSES)), default=None)
@click.option("--site", type=click.Choice(SUPPORTED_SITES), default=None)
@click.option("--remote", is_flag=True, default=False)
@click.option("--min-score", type=float, default=None,
              help="Minimum resume match score (0–100).")
@click.option("--search", "-q", default=None,
              help="Filter by keyword in title/company/description.")
@click.option("--limit", default=50, show_default=True)
@click.option("--offset", default=0)
def list_jobs(status, site, remote, min_score, search, limit, offset):
    """List saved jobs with optional filters."""
    jobs = get_jobs(
        status=status,
        site=site,
        remote_only=remote,
        min_score=min_score,
        search=search,
        limit=limit,
        offset=offset,
    )
    _print_jobs_table(jobs, title="Saved Jobs")


# ---------------------------------------------------------------------------
# show (job detail)
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("job_id")
def show(job_id):
    """Show full detail for a job by its database ID."""
    session_jobs = get_jobs(limit=10000)
    target = next((j for j in session_jobs if str(j.id) == str(job_id)), None)

    if not target:
        console.print(f"[red]Job #{job_id} not found.[/red]")
        return

    console.print()
    console.rule(f"[bold]{target.title}[/bold]")
    console.print(f"  [bold]Company:[/bold]  {target.company}")
    console.print(f"  [bold]Location:[/bold] {target.location}")
    console.print(f"  [bold]Level:[/bold]    {target.level or 'Unknown'}")
    console.print(f"  [bold]Site:[/bold]     {target.site}")
    console.print(f"  [bold]Remote:[/bold]   {'Yes' if target.is_remote else 'No'}")
    console.print(f"  [bold]Salary:[/bold]   {_salary_str(target) or 'Not listed'}")
    console.print(f"  [bold]Status:[/bold]   {target.status}")
    if target.match_score is not None:
        console.print(f"  [bold]Score:[/bold]    {target.match_score:.1f}%")
    if target.job_url:
        console.print(f"  [bold]URL:[/bold]      {target.job_url}")
    if target.date_posted:
        console.print(f"  [bold]Posted:[/bold]   {target.date_posted.date()}")

    # Skills breakdown
    skills = skills_from_db(target.required_skills, target.preferred_skills, target.skill_categories)
    if skills["required_skills"] or skills["preferred_skills"]:
        console.print()
        console.rule("[dim]Skills[/dim]")
        cats = skills["skill_categories"]
        if cats.get("technical"):
            console.print(f"  [bold cyan]Technical:[/bold cyan]  {', '.join(cats['technical'])}")
        if cats.get("process"):
            console.print(f"  [bold blue]Process:[/bold blue]    {', '.join(cats['process'])}")
        if cats.get("domain"):
            console.print(f"  [bold magenta]Domain:[/bold magenta]     {', '.join(cats['domain'])}")
        if cats.get("soft"):
            console.print(f"  [bold yellow]Soft:[/bold yellow]       {', '.join(cats['soft'])}")
        if skills["preferred_skills"]:
            console.print(f"  [dim]Preferred:  {', '.join(skills['preferred_skills'])}[/dim]")

    # Gap analysis
    resume = get_active_resume()
    if resume and resume.keywords:
        resume_keywords = [k.strip() for k in resume.keywords.split(",") if k.strip()]
        gap = analyse_gap_from_job(target, resume_keywords)
        console.print()
        console.rule("[dim]Gap Analysis vs Your Resume[/dim]")
        console.print(f"  Coverage: [green]{gap['coverage_score']:.0f}%[/green] of required skills")
        if gap["have"]:
            console.print(f"  [green]Have ✓[/green]    {', '.join(gap['have'])}")
        if gap["missing"]:
            console.print(f"  [red]Missing ✗[/red]  {', '.join(gap['missing'])}")
        if gap["optional_miss"]:
            console.print(f"  [yellow]Optional ✗[/yellow] {', '.join(gap['optional_miss'])}")

    if target.notes:
        console.print()
        console.rule("[dim]Notes[/dim]")
        console.print(target.notes)
    if target.description:
        console.print()
        console.rule("[dim]Description (first 800 chars)[/dim]")
        console.print(target.description[:800] + ("…" if len(target.description) > 800 else ""))
    console.print()


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("job_id")
@click.argument("status", type=click.Choice(list(VALID_STATUSES)))
@click.option("--note", default=None, help="Optional note to attach.")
def status(job_id, status, note):
    """Update the application status of a job."""
    ok = update_job_status(job_id, status, notes=note)
    if ok:
        console.print(f"[green]Job #{job_id} → {status}[/green]")
    else:
        console.print(f"[red]Job #{job_id} not found.[/red]")


# ---------------------------------------------------------------------------
# note
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("job_id")
@click.argument("text")
def note(job_id, text):
    """Append a timestamped note to a job."""
    ok = add_note(job_id, text)
    if ok:
        console.print(f"[green]Note added to job #{job_id}.[/green]")
    else:
        console.print(f"[red]Job #{job_id} not found.[/red]")


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("job_id")
@click.option("--yes", is_flag=True, help="Skip confirmation.")
def delete(job_id, yes):
    """Delete a job from the database."""
    if not yes:
        click.confirm(f"Delete job #{job_id}?", abort=True)
    ok = delete_job(job_id)
    if ok:
        console.print(f"[green]Job #{job_id} deleted.[/green]")
    else:
        console.print(f"[red]Job #{job_id} not found.[/red]")


# ---------------------------------------------------------------------------
# resume sub-group
# ---------------------------------------------------------------------------

@cli.group()
def resume():
    """Manage your resume for keyword matching."""


@resume.command(name="add")
@click.argument("filepath", type=click.Path(exists=True))
def resume_add(filepath):
    """Upload a resume (PDF, DOCX, or TXT) and re-score all saved jobs."""
    with console.status("[bold green]Parsing resume…[/bold green]"):
        r = add_resume(filepath)
    kw_count = len(r.keywords.split(",")) if r.keywords else 0
    console.print(f"[green]Resume '{r.filename}' loaded. {kw_count} keywords extracted.[/green]")
    if r.keywords:
        console.print(f"  [dim]{r.keywords}[/dim]")


@resume.command(name="show")
def resume_show():
    """Show the currently active resume."""
    r = get_active_resume()
    if not r:
        console.print("[yellow]No resume uploaded yet. Use: python main.py resume add <file>[/yellow]")
        return
    console.print(f"[bold]Active resume:[/bold] {r.filename}")
    console.print(f"  Uploaded: {r.uploaded_at}")
    if r.keywords:
        console.print(f"  Keywords ({len(r.keywords.split(','))}): {r.keywords}")


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--format", "fmt", type=click.Choice(["csv", "json"]), default="csv",
              show_default=True)
@click.option("--output", "-o", default=None,
              help="Output file path (default: exports/jobs.<fmt>).")
@click.option("--status", type=click.Choice(list(VALID_STATUSES)), default=None)
@click.option("--min-score", type=float, default=None)
def export(fmt, output, status, min_score):
    """Export jobs to CSV or JSON."""
    if output is None:
        output = f"exports/jobs.{fmt}"
    if fmt == "csv":
        count = export_to_csv(output, status=status, min_score=min_score)
    else:
        count = export_to_json(output, status=status, min_score=min_score)
    console.print(f"[green]Exported {count} job(s) → {output}[/green]")


# ---------------------------------------------------------------------------
# reclassify
# ---------------------------------------------------------------------------

@cli.command()
def reclassify():
    """Re-run level classifier and skill extractor on all saved jobs."""
    with console.status("[bold green]Reclassifying all jobs…[/bold green]"):
        count = reclassify_all_jobs()
    console.print(f"[green]Reclassified {count} job(s).[/green]")


# ---------------------------------------------------------------------------
# gaps
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--limit", default=20, show_default=True)
@click.option("--status", type=click.Choice(list(VALID_STATUSES)), default=None)
def gaps(limit, status):
    """Show your most common skill gaps across saved/applied jobs."""
    resume = get_active_resume()
    if not resume:
        console.print("[yellow]No resume uploaded. Run: python main.py resume add <file>[/yellow]")
        return

    missing = get_top_missing_skills(limit=limit)
    if not missing:
        console.print("[yellow]No gap data yet. Run 'reclassify' after uploading your resume.[/yellow]")
        return

    console.print()
    console.rule("[bold]Top Skill Gaps[/bold]")
    console.print(f"  [dim]Skills most frequently required by jobs that are missing from your resume[/dim]")
    console.print()

    t = Table(box=box.SIMPLE)
    t.add_column("Skill", min_width=30)
    t.add_column("Jobs requiring it", justify="right")
    for row in missing:
        t.add_row(row["skill"], str(row["count"]))
    console.print(t)


# ---------------------------------------------------------------------------
# suggest  (AI-powered resume improvement)
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--job-id", default=None, help="Suggest edits for one specific job (by DB id). Omit to analyse across all saved jobs.")
@click.option("--target", default=80, show_default=True, help="Target coverage % to reach.")
def suggest(job_id, target):
    """AI resume suggestions to reach target coverage (requires ANTHROPIC_API_KEY)."""
    if not agent.is_available():
        console.print("[yellow]ANTHROPIC_API_KEY not set. Add it to .env to enable AI suggestions.[/yellow]")
        return

    resume = get_active_resume()
    if not resume or not resume.raw_text:
        console.print("[yellow]No resume uploaded. Run: python main.py resume add <file>[/yellow]")
        return

    if job_id:
        # Per-job suggestions
        all_jobs = get_jobs(limit=10000)
        job = next((j for j in all_jobs if str(j.id) == str(job_id)), None)
        if not job:
            console.print(f"[red]Job #{job_id} not found.[/red]")
            return

        resume_keywords = [k.strip() for k in resume.keywords.split(",") if k.strip()]
        gap = analyse_gap_from_job(job, resume_keywords)

        if gap["coverage_score"] >= target:
            console.print(f"[green]Already at {gap['coverage_score']:.0f}% coverage — above target of {target}%.[/green]")
            return

        console.print(f"\n[bold]Generating suggestions for:[/bold] {job.title} @ {job.company}")
        console.print(f"  Current coverage: [red]{gap['coverage_score']:.0f}%[/red] → target: [green]{target}%[/green]")
        console.print(f"  Missing skills: {', '.join(gap['missing'])}\n")

        with console.status("[bold green]Asking Claude for resume edits…[/bold green]"):
            result = agent.suggest_resume_edits(
                resume_text=resume.raw_text,
                job_title=job.title,
                job_description=job.description or "",
                missing_skills=gap["missing"],
                have_skills=gap["have"],
                target_coverage=target,
            )

        if not result or "error" in result:
            console.print(f"[red]Agent error: {result.get('error') if result else 'no response'}[/red]")
            return

        console.print(f"[bold cyan]{result.get('summary', '')}[/bold cyan]\n")

        if result.get("rewrites"):
            console.rule("[bold]Bullet rewrites[/bold]")
            for r in result["rewrites"]:
                console.print(f"\n  [bold]{r.get('section', '')}[/bold]")
                if r.get("original"):
                    console.print(f"  [dim]Before:[/dim] {r['original']}")
                console.print(f"  [green]After:[/green]  {r['rewrite']}")
                console.print(f"  [dim]Adds:[/dim] {', '.join(r.get('skills_added', []))}")

        if result.get("new_bullets"):
            console.rule("[bold]New bullets to add[/bold]")
            for b in result["new_bullets"]:
                console.print(f"\n  [bold]{b.get('section', '')}[/bold]")
                console.print(f"  [green]+[/green] {b['bullet']}")
                console.print(f"  [dim]Adds:[/dim] {', '.join(b.get('skills_added', []))}")

        if result.get("quick_wins"):
            console.rule("[bold]Quick wins[/bold]")
            for w in result["quick_wins"]:
                console.print(f"  [yellow]→[/yellow] {w}")

        if result.get("genuine_gaps"):
            console.rule("[bold]Genuine gaps (not in your background)[/bold]")
            for g in result["genuine_gaps"]:
                console.print(f"  [red]✗[/red] {g}")

        est = result.get("estimated_coverage")
        if est:
            console.print(f"\n  [bold]Estimated coverage after changes:[/bold] [green]{est}%[/green]")

    else:
        # Aggregate suggestions across all jobs
        top_gaps = get_top_missing_skills(limit=15)
        if not top_gaps:
            console.print("[yellow]No gap data. Upload a resume and run 'reclassify' first.[/yellow]")
            return

        console.print(f"\n[bold]Generating portfolio-level resume suggestions…[/bold]")
        console.print(f"  Top missing skills: {', '.join(g['skill'] for g in top_gaps[:5])} …\n")

        with console.status("[bold green]Asking Claude for high-impact edits…[/bold green]"):
            result = agent.aggregate_resume_suggestions(
                resume_text=resume.raw_text,
                top_missing_skills=top_gaps,
                target_coverage=target,
            )

        if not result or "error" in result:
            console.print(f"[red]Agent error: {result.get('error') if result else 'no response'}[/red]")
            return

        console.print(f"[bold cyan]{result.get('summary', '')}[/bold cyan]\n")

        if result.get("high_impact_edits"):
            console.rule("[bold]High-impact edits (ranked by jobs affected)[/bold]")
            for e in result["high_impact_edits"]:
                console.print(f"\n  [bold yellow]{e.get('skill', '')}[/bold yellow]  [dim](affects {e.get('jobs_affected', '?')} jobs)[/dim]")
                console.print(f"  {e.get('suggestion', '')}")

        if result.get("section_recommendations"):
            console.rule("[bold]Section-level recommendations[/bold]")
            for r in result["section_recommendations"]:
                console.print(f"  [green]→[/green] {r}")

    console.print()


# ---------------------------------------------------------------------------
# advice  (AI application tips for a specific job)
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("job_id")
def advice(job_id):
    """AI application tips for a specific job (requires ANTHROPIC_API_KEY)."""
    if not agent.is_available():
        console.print("[yellow]ANTHROPIC_API_KEY not set. Add it to .env to enable AI advice.[/yellow]")
        return

    resume = get_active_resume()
    if not resume or not resume.raw_text:
        console.print("[yellow]No resume uploaded. Run: python main.py resume add <file>[/yellow]")
        return

    all_jobs = get_jobs(limit=10000)
    job = next((j for j in all_jobs if str(j.id) == str(job_id)), None)
    if not job:
        console.print(f"[red]Job #{job_id} not found.[/red]")
        return

    console.print(f"\n[bold]Application advice for:[/bold] {job.title} @ {job.company}\n")

    with console.status("[bold green]Asking Claude…[/bold green]"):
        result = agent.job_application_advice(
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

    if semantic and "score" in semantic:
        console.print(f"  [bold]Semantic match score:[/bold] [{'green' if semantic['score'] >= 60 else 'yellow' if semantic['score'] >= 40 else 'red'}]{semantic['score']}%[/]")
        console.print(f"  [dim]{semantic.get('rationale', '')}[/dim]\n")

    if not result or "error" in result:
        console.print(f"[red]Agent error: {result.get('error') if result else 'no response'}[/red]")
        return

    if result.get("tips"):
        console.rule("[bold]Tips[/bold]")
        for t in result["tips"]:
            console.print(f"\n  [bold green]→[/bold green] {t.get('tip', '')}")
            console.print(f"    [dim]{t.get('reason', '')}[/dim]")

    if result.get("talking_points"):
        console.rule("[bold]Talking points to highlight[/bold]")
        for tp in result["talking_points"]:
            console.print(f"  [cyan]•[/cyan] {tp}")

    if result.get("red_flags"):
        console.rule("[bold]Potential concerns to address[/bold]")
        for rf in result["red_flags"]:
            console.print(f"  [red]![/red] {rf}")

    console.print()


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------

@cli.command()
def stats():
    """Show database statistics and application funnel."""
    funnel = get_funnel_stats()
    by_site = get_stats_by_site()
    by_level = get_stats_by_level()
    score_dist = get_score_distribution()

    console.print()
    console.rule("[bold]Application Funnel[/bold]")
    console.print(f"  Total saved:       {funnel['total']}")
    console.print(f"  Applied:           {funnel['applied']}  "
                  f"({funnel['application_rate']}% of saved)")
    console.print(f"  Response rate:     [yellow]{funnel['response_rate']}%[/yellow]  "
                  f"(got a reply / applied)")
    console.print(f"  Interview rate:    [cyan]{funnel['interview_rate']}%[/cyan]")
    console.print(f"  Offer rate:        [green]{funnel['offer_rate']}%[/green]")
    console.print(f"  Rejection rate:    [red]{funnel['rejection_rate']}%[/red]")
    if funnel["avg_days_to_response"] is not None:
        console.print(f"  Avg days to reply: {funnel['avg_days_to_response']} days")

    if by_site:
        console.print()
        t_site = Table(title="By Site", box=box.SIMPLE)
        t_site.add_column("Site")
        t_site.add_column("Total", justify="right")
        t_site.add_column("Applied", justify="right")
        t_site.add_column("Response %", justify="right")
        for row in by_site:
            t_site.add_row(row["site"], str(row["total"]), str(row["applied"]),
                           f"{row['response_rate']}%")
        console.print(t_site)

    if by_level:
        console.print()
        t_level = Table(title="By Level", box=box.SIMPLE)
        t_level.add_column("Level")
        t_level.add_column("Total", justify="right")
        t_level.add_column("Applied", justify="right")
        t_level.add_column("Response %", justify="right")
        for row in by_level:
            t_level.add_row(row["level"], str(row["total"]), str(row["applied"]),
                            f"{row['response_rate']}%")
        console.print(t_level)

    if any(b["count"] > 0 for b in score_dist):
        console.print()
        t_score = Table(title="Match Score Distribution", box=box.SIMPLE)
        t_score.add_column("Score Range")
        t_score.add_column("Jobs", justify="right")
        for b in score_dist:
            if b["count"] > 0:
                t_score.add_row(b["range"], str(b["count"]))
        console.print(t_score)

    console.print()


if __name__ == "__main__":
    cli()
