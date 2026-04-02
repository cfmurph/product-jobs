"""Resume parser: extracts text and product-relevant keywords from PDF/DOCX files."""
import os
import re
import shutil
from pathlib import Path
from typing import Optional

from pdfminer.high_level import extract_text as pdf_extract
from docx import Document

try:
    import pypdf as _pypdf
    _HAVE_PYPDF = True
except ImportError:
    _HAVE_PYPDF = False

RESUME_DIR = Path(__file__).parent.parent.parent / "data" / "resumes"

# Product management keywords to look for / score against
PRODUCT_KEYWORDS: list[str] = [
    # Roles & seniority
    "product manager", "product management", "product lead", "product owner",
    "product strategy", "product roadmap", "product vision",
    # Discovery / research
    "user research", "customer discovery", "user interviews", "usability testing",
    "a/b testing", "experimentation", "data-driven",
    # Execution
    "agile", "scrum", "kanban", "sprint", "backlog", "prioritization",
    "go-to-market", "gtm", "launch", "mvp", "okr", "kpi", "metrics",
    # Technical
    "api", "sql", "data analysis", "analytics", "bi", "tableau", "looker",
    "machine learning", "ai", "ml", "python", "technical product manager",
    # Design / UX
    "ux", "ui", "design thinking", "figma", "prototyping", "wireframe",
    # Domains relevant to product roles
    "saas", "b2b", "b2c", "marketplace", "platform", "mobile", "web",
    "fintech", "healthtech", "edtech", "enterprise", "consumer",
    # Leadership
    "cross-functional", "stakeholder", "executive", "leadership",
    "team management", "mentoring",
]


def _extract_text_pdf(filepath: str) -> str:
    # Try pdfminer first (better layout handling)
    try:
        text = pdf_extract(filepath) or ""
        if text.strip():
            return text
    except Exception:
        pass

    # Fallback: pypdf
    if _HAVE_PYPDF:
        try:
            reader = _pypdf.PdfReader(filepath)
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception:
            pass

    return ""


def _extract_text_docx(filepath: str) -> str:
    try:
        doc = Document(filepath)
        return "\n".join(p.text for p in doc.paragraphs)
    except Exception:
        return ""


def _extract_text_txt(filepath: str) -> str:
    try:
        with open(filepath, encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""


def extract_text(filepath: str) -> str:
    """Extract plain text from a resume file (PDF, DOCX, or TXT)."""
    ext = Path(filepath).suffix.lower()
    if ext == ".pdf":
        return _extract_text_pdf(filepath)
    if ext in (".docx", ".doc"):
        return _extract_text_docx(filepath)
    return _extract_text_txt(filepath)


def extract_keywords(text: str, extra_keywords: list[str] | None = None) -> list[str]:
    """
    Return the subset of PRODUCT_KEYWORDS (plus any extras) that appear in the text.
    Case-insensitive whole-phrase matching.
    """
    keywords = PRODUCT_KEYWORDS[:]
    if extra_keywords:
        keywords.extend(k.lower() for k in extra_keywords)

    lower = text.lower()
    found = []
    for kw in keywords:
        pattern = r'\b' + re.escape(kw) + r'\b'
        if re.search(pattern, lower):
            found.append(kw)
    # Deduplicate while preserving order
    seen: set[str] = set()
    unique = []
    for k in found:
        if k not in seen:
            seen.add(k)
            unique.append(k)
    return unique


def score_job_against_resume(
    job_description: Optional[str],
    resume_keywords: list[str],
) -> tuple[float, list[str]]:
    """
    Return (score 0–100, matched_keywords).
    Score = (matched / total_resume_keywords) * 100, capped at 100.
    """
    if not job_description or not resume_keywords:
        return 0.0, []

    lower_desc = job_description.lower()
    matched = []
    for kw in resume_keywords:
        pattern = r'\b' + re.escape(kw) + r'\b'
        if re.search(pattern, lower_desc):
            matched.append(kw)

    if not resume_keywords:
        return 0.0, []

    score = round(min(len(matched) / len(resume_keywords) * 100, 100), 1)
    return score, matched


def save_resume_file(src_path: str) -> str:
    """Copy a resume file into data/resumes/ and return the destination path.
    If the file is already inside the target directory, return it as-is."""
    RESUME_DIR.mkdir(parents=True, exist_ok=True)
    dest = RESUME_DIR / Path(src_path).name
    if Path(src_path).resolve() != dest.resolve():
        shutil.copy2(src_path, dest)
    return str(dest)
