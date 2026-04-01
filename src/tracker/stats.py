"""
Response rate and funnel statistics.

Funnel:
  saved → applied → interviewing → offer
                               ↘ rejected

Metrics computed:
  - application_rate:  applied / saved (what % of saved jobs you actually applied to)
  - response_rate:     (interviewing + offer + rejected) / applied
  - interview_rate:    interviewing / applied
  - offer_rate:        offer / (interviewing or applied)
  - rejection_rate:    rejected / applied
  - avg_days_to_response: mean days from applied_at to responded_at

Breakdowns by: site, level
"""
import datetime
from typing import Optional

from src.db.models import Job, init_db, get_session


def _get_session():
    import os
    from pathlib import Path
    db_path = os.getenv("DB_PATH", "data/jobs.db")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = init_db(db_path)
    return get_session(engine)


def _pct(num: int, denom: int) -> float:
    return round(num / denom * 100, 1) if denom else 0.0


def get_funnel_stats() -> dict:
    session = _get_session()
    try:
        total   = session.query(Job).count()
        saved   = session.query(Job).filter(Job.status == "saved").count()
        applied = session.query(Job).filter(Job.status.in_(
            ["applied", "interviewing", "offer", "rejected"]
        )).count()
        interviewing = session.query(Job).filter(Job.status == "interviewing").count()
        offer        = session.query(Job).filter(Job.status == "offer").count()
        rejected     = session.query(Job).filter(Job.status == "rejected").count()
        archived     = session.query(Job).filter(Job.status == "archived").count()

        responded = interviewing + offer + rejected

        # Days to first response
        days_list = []
        for job in (
            session.query(Job)
            .filter(Job.applied_at.isnot(None), Job.responded_at.isnot(None))
            .all()
        ):
            delta = (job.responded_at - job.applied_at).days
            if delta >= 0:
                days_list.append(delta)

        avg_days = round(sum(days_list) / len(days_list), 1) if days_list else None

        return {
            "total": total,
            "saved": saved,
            "applied": applied,
            "interviewing": interviewing,
            "offer": offer,
            "rejected": rejected,
            "archived": archived,
            "responded": responded,
            "application_rate": _pct(applied, total),
            "response_rate": _pct(responded, applied),
            "interview_rate": _pct(interviewing, applied),
            "offer_rate": _pct(offer, max(interviewing, applied)),
            "rejection_rate": _pct(rejected, applied),
            "avg_days_to_response": avg_days,
        }
    finally:
        session.close()


def get_stats_by_site() -> list[dict]:
    session = _get_session()
    try:
        sites = [r[0] for r in session.query(Job.site).distinct().all() if r[0]]
        rows = []
        for site in sorted(sites):
            applied = session.query(Job).filter(
                Job.site == site,
                Job.status.in_(["applied", "interviewing", "offer", "rejected"])
            ).count()
            responded = session.query(Job).filter(
                Job.site == site,
                Job.status.in_(["interviewing", "offer", "rejected"])
            ).count()
            total = session.query(Job).filter(Job.site == site).count()
            rows.append({
                "site": site,
                "total": total,
                "applied": applied,
                "responded": responded,
                "response_rate": _pct(responded, applied),
            })
        return rows
    finally:
        session.close()


def get_stats_by_level() -> list[dict]:
    session = _get_session()
    try:
        levels = [r[0] for r in session.query(Job.level).distinct().all() if r[0]]
        rows = []
        level_order = [
            "APM", "PM", "Senior PM", "Staff PM", "Principal PM",
            "Group PM", "Director", "VP", "CPO", "TPM", "Unknown",
        ]
        for level in sorted(levels, key=lambda l: level_order.index(l) if l in level_order else 99):
            applied = session.query(Job).filter(
                Job.level == level,
                Job.status.in_(["applied", "interviewing", "offer", "rejected"])
            ).count()
            responded = session.query(Job).filter(
                Job.level == level,
                Job.status.in_(["interviewing", "offer", "rejected"])
            ).count()
            total = session.query(Job).filter(Job.level == level).count()
            rows.append({
                "level": level,
                "total": total,
                "applied": applied,
                "responded": responded,
                "response_rate": _pct(responded, applied),
            })
        return rows
    finally:
        session.close()


def get_top_missing_skills(limit: int = 15) -> list[dict]:
    """Rank skills most frequently missing across all saved/applied jobs."""
    import json
    session = _get_session()
    try:
        counter: dict[str, int] = {}
        for job in session.query(Job).filter(Job.gap_skills.isnot(None)).all():
            for skill in job.gap_skills.split(","):
                skill = skill.strip()
                if skill:
                    counter[skill] = counter.get(skill, 0) + 1
        ranked = sorted(counter.items(), key=lambda x: x[1], reverse=True)
        return [{"skill": s, "count": c} for s, c in ranked[:limit]]
    finally:
        session.close()


def get_score_distribution() -> list[dict]:
    """Return counts of jobs in 10-point score buckets."""
    session = _get_session()
    try:
        buckets = [0] * 11  # 0-9, 10-19, ..., 90-99, 100
        for job in session.query(Job).filter(Job.match_score.isnot(None)).all():
            idx = min(int(job.match_score // 10), 10)
            buckets[idx] += 1
        return [
            {"range": f"{i*10}–{i*10+9 if i < 10 else 100}", "count": buckets[i]}
            for i in range(11)
        ]
    finally:
        session.close()
