"""
Gap analysis: compare a job's required/preferred skills against your resume keywords.

Returns three buckets:
  - have:     skills the job requires that appear in your resume
  - missing:  skills the job requires that are NOT in your resume  ← the gaps
  - optional: preferred (nice-to-have) skills that are NOT in your resume
"""
import json
from typing import Optional

from src.classifier.skills import skills_from_db


def analyse_gap(
    required_skills: list[str],
    preferred_skills: list[str],
    resume_keywords: list[str],
) -> dict:
    """
    Returns:
    {
        have:          [...],   # required skills covered by resume
        missing:       [...],   # required skills NOT in resume  ← gaps
        optional_have: [...],   # preferred skills covered
        optional_miss: [...],   # preferred skills not covered
        gap_score:     float,   # % of required skills that are missing (0 = perfect fit)
        coverage_score: float,  # % of required skills covered (0–100)
    }
    """
    resume_lower = {k.lower() for k in resume_keywords}

    have = []
    missing = []
    for skill in required_skills:
        if skill.lower() in resume_lower:
            have.append(skill)
        else:
            missing.append(skill)

    optional_have = []
    optional_miss = []
    for skill in preferred_skills:
        if skill.lower() in resume_lower:
            optional_have.append(skill)
        else:
            optional_miss.append(skill)

    total_required = len(required_skills)
    coverage_score = round(len(have) / total_required * 100, 1) if total_required else 0.0
    gap_score = round(len(missing) / total_required * 100, 1) if total_required else 0.0

    return {
        "have": have,
        "missing": missing,
        "optional_have": optional_have,
        "optional_miss": optional_miss,
        "gap_score": gap_score,
        "coverage_score": coverage_score,
    }


def analyse_gap_from_job(job, resume_keywords: list[str]) -> dict:
    """Convenience wrapper that accepts a Job ORM object."""
    skills = skills_from_db(
        job.required_skills,
        job.preferred_skills,
        job.skill_categories,
    )
    return analyse_gap(
        required_skills=skills["required_skills"],
        preferred_skills=skills["preferred_skills"],
        resume_keywords=resume_keywords,
    )
