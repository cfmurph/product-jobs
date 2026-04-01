# product-jobs

A local tool for finding, classifying, and tracking **product management jobs** across LinkedIn, Indeed, Glassdoor, and ZipRecruiter. Includes a web UI and a CLI.

---

## Features

| Category | What it does |
|---|---|
| **Multi-board search** | Scrapes LinkedIn, Indeed, Glassdoor, ZipRecruiter via [python-jobspy](https://github.com/Bunsly/JobSpy) |
| **Level classification** | Auto-buckets every job: APM / PM / Senior PM / Staff PM / Principal PM / Group PM / Director / VP / CPO / TPM |
| **Skill extraction** | Pulls required vs preferred skills from job descriptions; categorised into Technical, Process, Domain, Soft |
| **Gap analysis** | Diffs job's required skills against your resume — shows what you have ✓ and what you're missing ✗ |
| **Resume scoring** | 0–100% keyword match score against your resume for every job |
| **Application tracker** | Track status: saved → applied → interviewing → offer / rejected |
| **Response rate stats** | Application funnel with response %, interview %, offer % — broken down by site and level |
| **Top gaps dashboard** | Skills most frequently missing across all saved jobs |
| **Web UI** | Full-featured browser interface at `localhost:5000` |
| **CLI** | Terminal interface for power users |
| **Export** | CSV and JSON export |

---

## Quick Start

### 1. Install

```bash
git clone https://github.com/cfmurph/product-jobs.git
cd product-jobs
pip install -r requirements.txt
```

### 2. Configure (optional)

```bash
cp .env.example .env
# Add LINKEDIN_EMAIL + LINKEDIN_PASSWORD for authenticated scraping
```

### 3. Launch the web UI

```bash
python web.py
# → open http://localhost:5000
```

### 4. Or use the CLI

```bash
python main.py search                                           # default PM titles, all boards
python main.py search --term "senior PM" --location "NYC"
python main.py list --min-score 40 --remote
python main.py show 42                                         # gap analysis in terminal
python main.py status 42 applied
python main.py gaps                                            # top missing skills
python main.py stats                                           # funnel + response rates
python main.py resume add /path/to/resume.pdf
python main.py export --format csv
```

---

## Web UI Pages

| Page | URL | What you see |
|---|---|---|
| **Dashboard** | `/` | Funnel stats, top gaps, by-site & by-level breakdowns, recent jobs |
| **Jobs** | `/jobs` | Filterable table: level, site, score, gap %, status, remote |
| **Job Detail** | `/jobs/<id>` | Skill breakdown, gap analysis, notes, status tracking |
| **Search** | `/search` | Trigger a live scrape from the browser |
| **Resume** | `/resume` | Upload, see detected keywords |

---

## Classification Details

### Job Level
Parsed from title (primary) then description (fallback):

```
APM → PM → Senior PM → Staff PM → Principal PM → Group PM → Director → VP → CPO
TPM (Technical Program Manager — separate track)
```

### Skill Categories
~150 skills across four buckets extracted from job descriptions:

| Category | Examples |
|---|---|
| **Technical** | SQL, Python, Tableau, A/B testing, APIs, ML, Amplitude |
| **Process** | Agile, roadmap, OKRs, user research, go-to-market, MVP |
| **Domain** | SaaS, B2B, fintech, marketplace, mobile, enterprise |
| **Soft** | Stakeholder management, cross-functional, executive communication |

Required vs preferred skills are split using section headers ("Requirements", "Nice to have", etc.).

### Gap Analysis
```
gap_score     = % of required skills NOT in your resume  (lower = better fit)
coverage_score = % of required skills covered by resume  (higher = better fit)
```

---

## Response Rate Tracking

The stats dashboard shows:
- **Application rate** — % of saved jobs you applied to
- **Response rate** — % of applications that got any reply (interview/offer/rejection)
- **Interview rate** — applications that reached an interview stage
- **Offer rate** — interviews that converted to an offer
- **Avg days to response**
- Breakdowns by job board and level

`responded_at` is automatically set when you mark a job as `interviewing`, `offer`, or `rejected`.

---

## Project Structure

```
product-jobs/
├── main.py              # CLI entry point
├── web.py               # Web UI launcher
├── requirements.txt
├── .env.example
├── web/
│   ├── app.py           # Flask routes
│   └── templates/       # Jinja2 templates (Tailwind CSS)
│       ├── base.html
│       ├── dashboard.html
│       ├── jobs.html
│       ├── job_detail.html
│       ├── search.html
│       └── resume.html
├── src/
│   ├── db/
│   │   └── models.py    # SQLAlchemy ORM (Job, Resume) + auto-migration
│   ├── classifier/
│   │   ├── level.py     # Job level classifier
│   │   └── skills.py    # Skill extractor + categoriser
│   ├── resume/
│   │   ├── parser.py    # PDF/DOCX/TXT parser + keyword extractor
│   │   └── gap.py       # Gap analysis
│   ├── scrapers/
│   │   └── jobspy_scraper.py
│   └── tracker/
│       ├── jobs.py      # Persistence, upsert, status, export
│       └── stats.py     # Funnel, response rates, top gaps
├── data/                # SQLite DB + uploaded resumes (gitignored)
└── exports/             # CSV/JSON exports (gitignored)
```

---

## CLI Reference

```
python main.py search        Search job boards (default: all PM titles)
python main.py list          List saved jobs with filters
python main.py show <id>     Full detail: skills, gap analysis, notes
python main.py status <id>   Update application status
python main.py note <id>     Add a timestamped note
python main.py delete <id>   Delete a job
python main.py gaps          Top skill gaps across all saved jobs
python main.py reclassify    Re-run classifiers on all existing jobs
python main.py resume add    Upload a resume
python main.py resume show   Show active resume keywords
python main.py export        Export to CSV or JSON
python main.py stats         Funnel stats + response rates by site/level
```

---

## Credentials

| | Without | With |
|---|---|---|
| **LinkedIn creds** | Public listings only | Authenticated scraping → more results, descriptions included |
| **Resume** | No scoring or gap analysis | Full match scoring, gap analysis, top gaps dashboard |

Add to `.env`:
```
LINKEDIN_EMAIL=you@example.com
LINKEDIN_PASSWORD=yourpassword
```
