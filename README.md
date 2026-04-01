# product-jobs

A local CLI tool for finding, scoring, and tracking **product management jobs** across LinkedIn, Indeed, Glassdoor, and ZipRecruiter — with optional resume-based keyword matching and a full application tracker.

---

## Features

- **Multi-board search** — scrapes LinkedIn, Indeed, Glassdoor, and ZipRecruiter via [python-jobspy](https://github.com/Bunsly/JobSpy)
- **Product-focused defaults** — pre-configured search terms for PM, Senior PM, Director of Product, VP of Product, and more
- **Resume scoring** — upload your resume (PDF, DOCX, or TXT) and every job gets a keyword match score (0–100%)
- **Application tracker** — save jobs locally in SQLite and track status: `saved → applied → interviewing → offer / rejected`
- **Notes** — timestamped notes on any job
- **Export** — dump your job list to CSV or JSON
- **Rich terminal UI** — color-coded tables via [rich](https://github.com/Textualize/rich)

---

## Quick Start

### 1. Clone and install dependencies

```bash
git clone https://github.com/cfmurph/product-jobs.git
cd product-jobs
pip install -r requirements.txt
```

### 2. Configure environment (optional)

```bash
cp .env.example .env
# Edit .env to add LinkedIn credentials and/or a proxy
```

LinkedIn credentials unlock authenticated scraping (more results, reduced rate-limiting). The tool works without them — unauthenticated public scraping is the default.

### 3. Run your first search

```bash
# Search all boards with default PM title list
python main.py search

# Search a specific term and location
python main.py search --term "senior product manager" --location "San Francisco, CA"

# Remote-only jobs on LinkedIn and Indeed
python main.py search --remote --sites linkedin --sites indeed

# Multiple terms
python main.py search --term "product lead" --term "group product manager"
```

### 4. Upload your resume (optional but recommended)

```bash
python main.py resume add /path/to/your-resume.pdf
```

After uploading, every job in the database is re-scored automatically. Use `--min-score` when listing to focus on the strongest matches.

### 5. List and filter saved jobs

```bash
# All jobs
python main.py list

# Only remote jobs with >40% keyword match
python main.py list --remote --min-score 40

# Filter by status
python main.py list --status applied

# Keyword search across title/company/description
python main.py list --search fintech
```

### 6. Track your applications

```bash
# Update status (saved / applied / interviewing / offer / rejected / archived)
python main.py status 42 applied

# Add a note
python main.py note 42 "Spoke with recruiter — panel interview next week"

# View full job detail
python main.py show 42
```

### 7. Export

```bash
python main.py export --format csv          # → exports/jobs.csv
python main.py export --format json         # → exports/jobs.json
python main.py export --format csv --status applied --min-score 30
```

### 8. Stats

```bash
python main.py stats
```

---

## Credentials

You do **not** need credentials to use this tool.

| Credential | Required | Effect |
|---|---|---|
| `LINKEDIN_EMAIL` + `LINKEDIN_PASSWORD` | No | Authenticated LinkedIn scraping → more results, job descriptions included, less rate-limiting |
| Resume file | No | Enables keyword match scoring (0–100%) against job descriptions |

If you want to add LinkedIn credentials:

1. Copy `.env.example` → `.env`
2. Fill in `LINKEDIN_EMAIL` and `LINKEDIN_PASSWORD`
3. Re-run any `search` command

> **Note:** LinkedIn occasionally flags automated logins. Use a dedicated account or a proxy (`PROXY=http://...` in `.env`) if you hit blocks.

---

## Project Structure

```
product-jobs/
├── main.py                    # CLI entry point
├── requirements.txt
├── .env.example               # Template — copy to .env and fill in
├── data/
│   ├── jobs.db                # SQLite database (auto-created)
│   └── resumes/               # Uploaded resume files
├── exports/                   # CSV / JSON exports
└── src/
    ├── db/
    │   └── models.py          # SQLAlchemy ORM (Job, Resume)
    ├── scrapers/
    │   └── jobspy_scraper.py  # JobSpy wrapper + product-specific search terms
    ├── resume/
    │   └── parser.py          # PDF/DOCX parser + keyword extractor + scorer
    └── tracker/
        └── jobs.py            # Persistence, status updates, export, stats
```

---

## Application Status Flow

```
saved → applied → interviewing → offer
                              ↘ rejected
         ↘ archived (any time)
```

---

## Resume Scoring

When a resume is active, each job's description is scanned for ~60 product management keywords (agile, OKR, roadmap, user research, A/B testing, SQL, etc.). The match score is:

```
score = (keywords_in_jd ∩ keywords_in_resume) / total_resume_keywords × 100
```

Use `--min-score 30` (or higher) to surface the strongest matches.

---

## All Commands

```
python main.py --help

Commands:
  search    Search job boards for product management roles
  list      List saved jobs (filterable by status, site, remote, score, keyword)
  show      Full detail view for one job
  status    Update application status
  note      Append a timestamped note
  delete    Remove a job
  resume    add / show resume
  export    Export to CSV or JSON
  stats     Summary statistics
```

---

## Dependencies

| Package | Purpose |
|---|---|
| python-jobspy | Multi-board job scraping |
| SQLAlchemy | SQLite ORM |
| pdfminer.six | PDF text extraction |
| python-docx | DOCX text extraction |
| rich | Terminal tables and formatting |
| click | CLI framework |
| python-dotenv | `.env` file loading |
