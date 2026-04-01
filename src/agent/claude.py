"""
Claude agent layer.

Three capabilities:
  1. suggest_resume_edits()  — given a job + your resume, return specific
                               bullet rewrites that close the gap to a target
                               coverage score (default 80%).
  2. semantic_match_score()  — meaning-aware match score (0–100) that handles
                               synonyms keyword matching misses.
  3. job_application_advice() — 3–5 concrete tips for applying to a specific job.

All functions return None gracefully if ANTHROPIC_API_KEY is not set,
so the rest of the app works without the key.
"""
import json
import os
from typing import Optional

_CLIENT = None


def _client():
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic
        _CLIENT = anthropic.Anthropic(api_key=api_key)
        return _CLIENT
    except ImportError:
        return None


# Fast / cheap model for suggestions — upgrade to claude-sonnet-4-5 for richer output
_FAST_MODEL = "claude-haiku-4-5-20251001"
_SMART_MODEL = "claude-sonnet-4-5-20250929"


def is_available() -> bool:
    """Return True if the Anthropic key is configured and the SDK is installed."""
    return _client() is not None


def suggest_resume_edits(
    resume_text: str,
    job_title: str,
    job_description: str,
    missing_skills: list[str],
    have_skills: list[str],
    target_coverage: int = 80,
) -> Optional[dict]:
    """
    Ask Claude to suggest specific resume bullet rewrites that would
    naturally cover the missing skills and reach target_coverage %.

    Returns:
    {
        "summary": str,          # 1-sentence overall assessment
        "rewrites": [
            {
                "section": str,      # e.g. "Experience — Acme Corp"
                "original": str,     # best-guess at existing bullet (may be blank)
                "rewrite": str,      # suggested new bullet
                "skills_added": [...] # which missing skills this covers
            }
        ],
        "new_bullets": [
            {
                "section": str,       # where to add it
                "bullet": str,        # entirely new bullet point
                "skills_added": [...]
            }
        ],
        "quick_wins": [str],   # simple word/phrase additions (no full rewrite needed)
        "estimated_coverage": int,   # estimated coverage % after changes
    }
    Returns None if the API is unavailable or the call fails.
    """
    client = _client()
    if not client:
        return None

    missing_str = ", ".join(missing_skills) if missing_skills else "none"
    have_str = ", ".join(have_skills) if have_skills else "none"

    prompt = f"""You are a product management career coach helping a candidate improve their resume.

## Job
Title: {job_title}

Description (first 2000 chars):
{job_description[:2000]}

## Candidate's resume
{resume_text[:3000]}

## Gap analysis
Skills the job requires that the candidate ALREADY has: {have_str}
Skills the job requires that are MISSING from the resume: {missing_str}

Current coverage: {len(have_skills)}/{len(have_skills)+len(missing_skills)} required skills = {round(len(have_skills)/max(len(have_skills)+len(missing_skills),1)*100)}%
Target coverage: {target_coverage}%

## Your task
Suggest the MINIMUM edits to the resume to reach {target_coverage}% coverage.
For each missing skill, either:
  a) Rewrite an existing bullet to naturally incorporate it (preferred — don't invent experience)
  b) Suggest a new bullet if the experience clearly exists but isn't captured

Rules:
- Only suggest edits that reflect experience the candidate actually has based on their resume
- Be specific — give the full rewritten bullet, not vague advice
- Prefer adding skills to existing bullets over adding new sections
- If a missing skill genuinely doesn't appear anywhere in the resume, flag it as a gap to address separately

Respond in this exact JSON format (no markdown, raw JSON only):
{{
  "summary": "one sentence overall assessment",
  "rewrites": [
    {{
      "section": "section name and company/role",
      "original": "the existing bullet or phrase being changed",
      "rewrite": "the full rewritten bullet",
      "skills_added": ["skill1", "skill2"]
    }}
  ],
  "new_bullets": [
    {{
      "section": "where to add this",
      "bullet": "full new bullet text",
      "skills_added": ["skill1"]
    }}
  ],
  "quick_wins": ["Add 'OKRs' to your skills section", "Mention A/B testing in your Stripe bullet"],
  "estimated_coverage": 85,
  "genuine_gaps": ["skills that really aren't in your background at all"]
}}"""

    try:
        msg = client.messages.create(
            model=_SMART_MODEL,
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except Exception as exc:
        return {"error": str(exc)}


def semantic_match_score(
    resume_text: str,
    job_description: str,
    job_title: str,
) -> Optional[dict]:
    """
    Ask Claude for a meaning-aware match score that handles synonyms and
    paraphrasing that pure keyword matching misses.

    Returns:
    {
        "score": int (0–100),
        "rationale": str,
        "strengths": [str],
        "weaknesses": [str],
    }
    """
    client = _client()
    if not client:
        return None

    prompt = f"""You are evaluating how well a candidate's resume matches a job description.

Job title: {job_title}
Job description (first 1500 chars): {job_description[:1500]}

Candidate resume (first 2000 chars): {resume_text[:2000]}

Score the match from 0–100 based on MEANING, not just keywords.
For example: "managed cross-functional teams" should match "stakeholder management".

Respond in this exact JSON (raw, no markdown):
{{
  "score": 72,
  "rationale": "2–3 sentence explanation",
  "strengths": ["strength 1", "strength 2", "strength 3"],
  "weaknesses": ["weakness 1", "weakness 2"]
}}"""

    try:
        msg = client.messages.create(
            model=_FAST_MODEL,
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except Exception as exc:
        return {"error": str(exc)}


def job_application_advice(
    resume_text: str,
    job_title: str,
    job_description: str,
    company: str,
) -> Optional[dict]:
    """
    Generate 3–5 concrete, specific tips for applying to this role.

    Returns:
    {
        "tips": [
            {"tip": str, "reason": str}
        ],
        "talking_points": [str],   # things to highlight in cover letter / interview
        "red_flags": [str],        # potential concerns to address proactively
    }
    """
    client = _client()
    if not client:
        return None

    prompt = f"""You are a product management career coach.

Candidate resume (first 2000 chars): {resume_text[:2000]}

Role: {job_title} at {company}
Job description (first 1500 chars): {job_description[:1500]}

Give 3–5 specific, actionable tips for this candidate applying to this exact role.
Be concrete — reference their actual experience and the specific job requirements.

Respond in raw JSON (no markdown):
{{
  "tips": [
    {{"tip": "specific action to take", "reason": "why this matters for this role"}}
  ],
  "talking_points": [
    "specific experience from your resume to highlight for this role"
  ],
  "red_flags": [
    "potential gap or concern to address proactively"
  ]
}}"""

    try:
        msg = client.messages.create(
            model=_FAST_MODEL,
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except Exception as exc:
        return {"error": str(exc)}


def aggregate_resume_suggestions(
    resume_text: str,
    top_missing_skills: list[str],
    target_coverage: int = 80,
) -> Optional[dict]:
    """
    Look across ALL saved jobs' gap data and suggest resume edits that
    would have the broadest impact (close gaps for the most jobs at once).

    top_missing_skills: ranked list from get_top_missing_skills()

    Returns:
    {
        "summary": str,
        "high_impact_edits": [
            {
                "skill": str,
                "jobs_affected": int,
                "suggestion": str   # how to add this to the resume
            }
        ],
        "section_recommendations": [str],
    }
    """
    client = _client()
    if not client:
        return None

    skills_str = "\n".join(f"- {s['skill']} (missing in {s['count']} jobs)" for s in top_missing_skills[:15])

    prompt = f"""You are a product management career coach doing a portfolio-level resume review.

Candidate resume (first 2500 chars):
{resume_text[:2500]}

Skills most frequently missing across all saved job applications (ranked by frequency):
{skills_str}

Target: reach {target_coverage}% skill coverage across most jobs.

Suggest the highest-leverage edits to this resume — changes that cover multiple
frequently-missing skills at once. Focus on what's achievable given the candidate's
actual background shown in the resume.

Respond in raw JSON (no markdown):
{{
  "summary": "overall assessment in 2 sentences",
  "high_impact_edits": [
    {{
      "skill": "the skill being added",
      "jobs_affected": 12,
      "suggestion": "specific rewrite or addition — quote the resume section and show the change"
    }}
  ],
  "section_recommendations": [
    "Add a 'Core Competencies' section listing: roadmap, OKRs, stakeholder management, A/B testing",
    "other section-level recommendations"
  ]
}}"""

    try:
        msg = client.messages.create(
            model=_SMART_MODEL,
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except Exception as exc:
        return {"error": str(exc)}
