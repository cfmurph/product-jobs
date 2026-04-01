"""
Skill extractor for job descriptions.

Extracts:
  - required_skills: skills from the "Requirements" / "Qualifications" section
  - preferred_skills: skills from "Nice to have" / "Preferred" section
  - skill_categories: {technical, process, domain, soft} — all skills categorised

Returns everything as plain lists (JSON-serialisable).
"""
import json
import re
from typing import Optional

# ---------------------------------------------------------------------------
# Skill taxonomy
# ---------------------------------------------------------------------------

TECHNICAL_SKILLS: list[str] = [
    "sql", "python", "r", "excel", "tableau", "looker", "power bi", "dbt",
    "bigquery", "snowflake", "redshift", "spark", "airflow",
    "api", "rest api", "graphql", "webhooks",
    "machine learning", "ml", "ai", "llm", "nlp", "deep learning",
    "a/b testing", "experimentation", "statistics", "hypothesis testing",
    "data analysis", "data science", "analytics", "bi", "reporting",
    "amplitude", "mixpanel", "segment", "heap", "google analytics",
    "jira", "confluence", "notion", "linear", "asana",
    "figma", "sketch", "invision", "prototyping", "wireframing",
    "html", "css", "javascript", "react", "ios", "android",
    "aws", "gcp", "azure", "cloud",
]

PROCESS_SKILLS: list[str] = [
    "agile", "scrum", "kanban", "sprint planning", "backlog refinement",
    "roadmap", "product roadmap", "roadmapping",
    "okr", "okrs", "kpi", "kpis", "metrics", "success metrics",
    "go-to-market", "gtm", "product launch", "launch",
    "mvp", "discovery", "user research", "customer discovery",
    "user interviews", "usability testing", "ux research",
    "prioritization", "prioritisation", "rice", "ice scoring",
    "product strategy", "product vision", "product thinking",
    "requirements gathering", "product requirements", "prd",
    "feature definition", "acceptance criteria",
]

DOMAIN_SKILLS: list[str] = [
    "saas", "b2b", "b2c", "b2b2c", "marketplace", "platform",
    "consumer", "enterprise", "smb", "mid-market",
    "mobile", "web", "desktop",
    "fintech", "payments", "banking", "insurance",
    "healthtech", "health tech", "healthcare", "medtech",
    "edtech", "ed tech", "education",
    "e-commerce", "ecommerce", "retail",
    "developer tools", "devtools", "developer platform",
    "data platform", "infrastructure",
    "growth", "growth product", "monetisation", "monetization",
    "international", "localization", "globalization",
]

SOFT_SKILLS: list[str] = [
    "stakeholder management", "stakeholder alignment", "executive communication",
    "cross-functional", "cross functional", "collaboration",
    "leadership", "team leadership", "people management", "mentoring", "coaching",
    "communication", "written communication", "presentation skills",
    "influence without authority", "influencing",
    "strategic thinking", "problem solving", "critical thinking",
    "customer empathy", "customer focus", "customer-centric",
    "data-driven", "analytical mindset",
    "bias for action", "ownership", "accountability",
    "ambiguity", "navigating ambiguity", "fast-paced",
]

ALL_SKILLS: list[str] = TECHNICAL_SKILLS + PROCESS_SKILLS + DOMAIN_SKILLS + SOFT_SKILLS

# Map each skill to its category for fast lookup
_SKILL_CATEGORY: dict[str, str] = {}
for _s in TECHNICAL_SKILLS:
    _SKILL_CATEGORY[_s] = "technical"
for _s in PROCESS_SKILLS:
    _SKILL_CATEGORY[_s] = "process"
for _s in DOMAIN_SKILLS:
    _SKILL_CATEGORY[_s] = "domain"
for _s in SOFT_SKILLS:
    _SKILL_CATEGORY[_s] = "soft"

# ---------------------------------------------------------------------------
# Section splitter
# ---------------------------------------------------------------------------

_REQUIRED_HEADERS = re.compile(
    r"(required|must.have|minimum qualifications?|basic qualifications?|"
    r"what you.ll need|what we.re looking for|responsibilities|"
    r"qualifications?|requirements?)",
    re.IGNORECASE,
)

_PREFERRED_HEADERS = re.compile(
    r"(preferred|nice.to.have|bonus|plus|desired|"
    r"additional qualifications?|what would be great)",
    re.IGNORECASE,
)


def _split_sections(description: str) -> tuple[str, str]:
    """
    Split description into (required_text, preferred_text).
    Falls back to full description / empty string if sections can't be found.
    """
    lines = description.splitlines()
    required_lines: list[str] = []
    preferred_lines: list[str] = []
    current: str = "required"  # default bucket before any header is found

    for line in lines:
        stripped = line.strip()
        if _PREFERRED_HEADERS.search(stripped):
            current = "preferred"
            continue
        if _REQUIRED_HEADERS.search(stripped):
            current = "required"
            continue
        if current == "required":
            required_lines.append(line)
        else:
            preferred_lines.append(line)

    required_text = "\n".join(required_lines) if required_lines else description
    preferred_text = "\n".join(preferred_lines)
    return required_text, preferred_text


# ---------------------------------------------------------------------------
# Core extractor
# ---------------------------------------------------------------------------

def _find_skills_in_text(text: str) -> list[str]:
    lower = text.lower()
    found = []
    for skill in ALL_SKILLS:
        pattern = r'\b' + re.escape(skill) + r'\b'
        if re.search(pattern, lower):
            found.append(skill)
    # Deduplicate preserving order
    seen: set[str] = set()
    return [s for s in found if not (s in seen or seen.add(s))]  # type: ignore[func-returns-value]


def extract_skills(description: Optional[str]) -> dict:
    """
    Parse a job description and return:
    {
        required_skills: [...],
        preferred_skills: [...],
        skill_categories: {technical: [...], process: [...], domain: [...], soft: [...]},
    }
    All values are plain Python lists.
    """
    if not description:
        return {
            "required_skills": [],
            "preferred_skills": [],
            "skill_categories": {"technical": [], "process": [], "domain": [], "soft": []},
        }

    required_text, preferred_text = _split_sections(description)

    required_skills = _find_skills_in_text(required_text)
    preferred_skills = [s for s in _find_skills_in_text(preferred_text) if s not in required_skills]

    all_found = list(dict.fromkeys(required_skills + preferred_skills))
    categories: dict[str, list[str]] = {"technical": [], "process": [], "domain": [], "soft": []}
    for skill in all_found:
        cat = _SKILL_CATEGORY.get(skill, "technical")
        categories[cat].append(skill)

    return {
        "required_skills": required_skills,
        "preferred_skills": preferred_skills,
        "skill_categories": categories,
    }


def skills_to_json(skills_dict: dict) -> tuple[str, str, str]:
    """Serialize the extract_skills result to three JSON strings for DB storage."""
    return (
        json.dumps(skills_dict.get("required_skills", [])),
        json.dumps(skills_dict.get("preferred_skills", [])),
        json.dumps(skills_dict.get("skill_categories", {})),
    )


def skills_from_db(required_json: Optional[str], preferred_json: Optional[str],
                   categories_json: Optional[str]) -> dict:
    """Deserialize from DB strings back to dicts/lists."""
    def _load(s):
        try:
            return json.loads(s) if s else []
        except Exception:
            return []

    def _load_dict(s):
        try:
            return json.loads(s) if s else {}
        except Exception:
            return {}

    return {
        "required_skills": _load(required_json),
        "preferred_skills": _load(preferred_json),
        "skill_categories": _load_dict(categories_json),
    }
