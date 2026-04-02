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
    # Re-check every time in case the env var was set after module import
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    # Return cached client only if the key matches what we built it with
    if _CLIENT is not None:
        return _CLIENT
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


def chat(
    messages: list[dict],
    resume_text: str = "",
    job_context: dict | None = None,
) -> Optional[str]:
    """
    General-purpose chat with conversation history.

    messages: list of {"role": "user"|"assistant", "content": str}
    resume_text: current resume text (injected as system context)
    job_context: optional {"title": str, "company": str, "description": str,
                            "missing": [...], "have": [...]}

    Returns the assistant reply string, or None on failure.
    """
    client = _client()
    if not client:
        return None

    system_parts = [
        "You are a product management career coach helping a candidate improve their resume and job search.",
        "Be specific, concise, and actionable. Reference the candidate's actual resume content when making suggestions.",
        "When suggesting resume edits, always show the full rewritten bullet — not vague advice.",
    ]

    if resume_text:
        system_parts.append(f"\n## Candidate's current resume\n{resume_text[:3000]}")

    if job_context:
        system_parts.append(
            f"\n## Current job context\n"
            f"Role: {job_context.get('title', '')} at {job_context.get('company', '')}\n"
            f"Skills candidate has: {', '.join(job_context.get('have', []))}\n"
            f"Skills missing from resume: {', '.join(job_context.get('missing', []))}"
        )
        if job_context.get("description"):
            system_parts.append(f"Job description (first 1000 chars): {job_context['description'][:1000]}")

    system_prompt = "\n".join(system_parts)

    try:
        msg = client.messages.create(
            model=_SMART_MODEL,
            max_tokens=1000,
            system=system_prompt,
            messages=messages,
        )
        return msg.content[0].text
    except Exception as exc:
        return f"Error: {exc}"


def apply_edit_to_resume(
    resume_text: str,
    instruction: str,
) -> Optional[str]:
    """
    Apply a specific edit instruction to the resume text and return
    the full updated resume.

    instruction: e.g. "Add 'OKRs' to the Stripe bullet in Experience"
    Returns the full updated resume text.
    """
    client = _client()
    if not client:
        return None

    prompt = f"""You are editing a resume. Apply the following instruction to the resume text below.
Return ONLY the full updated resume text — no explanation, no markdown fences, just the resume.

Instruction: {instruction}

Resume:
{resume_text}"""

    try:
        msg = client.messages.create(
            model=_SMART_MODEL,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()
    except Exception as exc:
        return None


def stream_chat(
    messages: list[dict],
    resume_text: str = "",
    job_context: dict | None = None,
):
    """
    Streaming version of chat(). Yields text chunks as they arrive from Claude.
    Used for Server-Sent Events (SSE) so the UI updates token-by-token.
    """
    client = _client()
    if not client:
        yield "Error: ANTHROPIC_API_KEY not configured."
        return

    system_parts = [
        "You are a product management career coach helping a candidate improve their resume and job search.",
        "Be specific, concise, and actionable. Reference the candidate's actual resume content when making suggestions.",
        "When suggesting resume edits, show the FULL rewritten bullet or section — not vague advice.",
        "When you propose a specific rewrite wrap it in <suggestion> tags so the UI can offer a one-click apply button.",
        "Example: Here's a stronger version: <suggestion>Led cross-functional roadmap planning across 4 teams, aligning stakeholders on quarterly OKRs and shipping 3 major features on time.</suggestion>",
    ]

    if resume_text:
        system_parts.append(f"\n## Candidate's current resume\n{resume_text}")

    if job_context:
        system_parts.append(
            f"\n## Current job context\n"
            f"Role: {job_context.get('title', '')} at {job_context.get('company', '')}\n"
            f"Skills candidate has: {', '.join(job_context.get('have', []))}\n"
            f"Skills missing from resume: {', '.join(job_context.get('missing', []))}"
        )
        if job_context.get("description"):
            system_parts.append(f"Job description (first 1500 chars): {job_context['description'][:1500]}")

    try:
        with client.messages.stream(
            model=_SMART_MODEL,
            max_tokens=1200,
            system="\n".join(system_parts),
            messages=messages,
        ) as stream:
            for text in stream.text_stream:
                yield text
    except Exception as exc:
        yield f"\nError: {exc}"


def suggest_inline(
    resume_text: str,
    selected_text: str,
    instruction: str,
    job_context: dict | None = None,
) -> Optional[dict]:
    """
    Given a selected chunk of the resume and an instruction, return:
    {
        "original": str,   # the original selected text
        "suggestion": str, # the rewritten version
        "explanation": str # why this is better
    }
    """
    client = _client()
    if not client:
        return None

    job_section = ""
    if job_context:
        job_section = (
            f"\nJob targeting: {job_context.get('title', '')} at {job_context.get('company', '')}\n"
            f"Skills to incorporate if possible: {', '.join(job_context.get('missing', []))}"
        )

    prompt = f"""You are editing a resume. Rewrite ONLY the selected text according to the instruction.

Full resume (for context):
{resume_text}
{job_section}

Selected text to rewrite:
{selected_text}

Instruction: {instruction}

Respond in raw JSON only (no markdown):
{{
  "original": "the exact selected text",
  "suggestion": "the full rewritten replacement",
  "explanation": "one sentence explaining the improvement"
}}"""

    try:
        msg = client.messages.create(
            model=_SMART_MODEL,
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except Exception:
        return None


def generate_resume(
    resume_text: str,
    conversation_history: list[dict],
    job_context: dict | None = None,
    format: str = "text",
) -> Optional[str]:
    """
    Produce a polished, complete resume incorporating all changes discussed
    in the conversation. 

    format: "text" (plain) or "markdown"
    Returns the full resume as a string.
    """
    client = _client()
    if not client:
        return None

    job_section = ""
    if job_context:
        job_section = (
            f"\nOptimise for: {job_context.get('title', '')} at {job_context.get('company', '')}\n"
            f"Skills to incorporate: {', '.join(job_context.get('missing', []))}"
        )

    # Summarise conversation so Claude knows what was agreed
    convo_summary = ""
    if conversation_history:
        lines = []
        for m in conversation_history[-20:]:  # last 20 messages
            role = "User" if m["role"] == "user" else "Claude"
            lines.append(f"{role}: {m['content'][:300]}")
        convo_summary = "\n".join(lines)

    prompt = f"""You are a professional resume writer for product managers.

Rewrite the resume below, incorporating all improvements discussed in the conversation.
Produce a clean, complete, ATS-friendly resume ready to send.
{job_section}

Original resume:
{resume_text}

Conversation history (improvements discussed):
{convo_summary}

Rules:
- Keep all factual content — do NOT invent experience or companies
- Strengthen weak bullets with stronger action verbs and quantifiable results where present
- Naturally incorporate any skills from the missing list if they genuinely appear in the experience
- Use standard sections: Summary, Experience, Education, Skills
- {'Use markdown formatting with ## headers and - bullets' if format == 'markdown' else 'Plain text, standard resume format'}
- Return ONLY the resume — no preamble, no explanation

Write the full updated resume now:"""

    try:
        msg = client.messages.create(
            model=_SMART_MODEL,
            max_tokens=3000,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()
    except Exception as exc:
        return None


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
