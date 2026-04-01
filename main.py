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

load_dotenv()

from src.scrapers.jobspy_scraper import search_jobs, search_product_jobs, SUPPORTED_SITES
from src.tracker.jobs import (
    upsert_jobs, get_jobs, update_job_status, add_note, delete_job,
    add_resume, get_active_resume, export_to_csv, export_to_json,
    get_stats, VALID_STATUSES,
)

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
    table.add_column("Title", min_width=28, max_width=40)
    table.add_column("Company", min_width=16, max_width=24)
    table.add_column("Location", min_width=14, max_width=22)
    table.add_column("Site", width=10)
    table.add_column("Salary", width=14)
    table.add_column("Score", width=6)
    table.add_column("Status", width=12)
    table.add_column("Remote", width=7)

    for job in jobs:
        score = f"{job.match_score:.0f}%" if job.match_score is not None else ""
        color = STATUS_COLORS.get(job.status or "saved", "white")
        remote = "[green]✓[/green]" if job.is_remote else ""
        table.add_row(
            str(job.id),
            job.title or "",
            job.company or "",
            job.location or "",
            job.site or "",
            _salary_str(job),
            score,
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
    jobs = get_jobs(limit=1)
    # Fetch all to find by id — small db so fine
    session_jobs = get_jobs(limit=10000)
    target = next((j for j in session_jobs if str(j.id) == str(job_id)), None)

    if not target:
        console.print(f"[red]Job #{job_id} not found.[/red]")
        return

    console.print()
    console.rule(f"[bold]{target.title}[/bold]")
    console.print(f"  [bold]Company:[/bold]  {target.company}")
    console.print(f"  [bold]Location:[/bold] {target.location}")
    console.print(f"  [bold]Site:[/bold]     {target.site}")
    console.print(f"  [bold]Remote:[/bold]   {'Yes' if target.is_remote else 'No'}")
    console.print(f"  [bold]Salary:[/bold]   {_salary_str(target) or 'Not listed'}")
    console.print(f"  [bold]Status:[/bold]   {target.status}")
    if target.match_score is not None:
        console.print(f"  [bold]Score:[/bold]    {target.match_score:.1f}%")
    if target.matched_keywords:
        console.print(f"  [bold]Keywords:[/bold] {target.matched_keywords}")
    if target.job_url:
        console.print(f"  [bold]URL:[/bold]      {target.job_url}")
    if target.date_posted:
        console.print(f"  [bold]Posted:[/bold]   {target.date_posted.date()}")
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
# stats
# ---------------------------------------------------------------------------

@cli.command()
def stats():
    """Show database statistics."""
    s = get_stats()
    console.print()
    console.rule("[bold]Job Search Stats[/bold]")
    console.print(f"  [bold]Total jobs:[/bold] {s['total']}")
    console.print()

    t_status = Table(title="By Status", box=box.SIMPLE)
    t_status.add_column("Status")
    t_status.add_column("Count", justify="right")
    for status_key, count in s["by_status"].items():
        color = STATUS_COLORS.get(status_key, "white")
        t_status.add_row(f"[{color}]{status_key}[/{color}]", str(count))
    console.print(t_status)

    t_site = Table(title="By Site", box=box.SIMPLE)
    t_site.add_column("Site")
    t_site.add_column("Count", justify="right")
    for site_key, count in s["by_site"].items():
        t_site.add_row(site_key, str(count))
    console.print(t_site)

    console.print(f"  [bold]Remote:[/bold] {s['remote']}")
    console.print()


if __name__ == "__main__":
    cli()
