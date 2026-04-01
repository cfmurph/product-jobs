"""SQLAlchemy ORM models."""
import datetime
from sqlalchemy import (
    Boolean, Column, DateTime, Float, Integer, String, Text, create_engine
)
from sqlalchemy.orm import DeclarativeBase, Session


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String, unique=True, nullable=False)  # site-specific id
    site = Column(String, nullable=False)                  # linkedin / indeed / glassdoor / zip_recruiter
    title = Column(String, nullable=False)
    company = Column(String)
    location = Column(String)
    job_type = Column(String)                              # full-time / contract / etc.
    is_remote = Column(Boolean, default=False)
    salary_min = Column(Float)
    salary_max = Column(Float)
    salary_currency = Column(String, default="USD")
    salary_interval = Column(String)                       # yearly / hourly / monthly
    description = Column(Text)
    job_url = Column(String)
    date_posted = Column(DateTime)
    scraped_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Application tracking
    status = Column(String, default="saved")               # saved / applied / interviewing / offer / rejected / archived
    notes = Column(Text)
    applied_at = Column(DateTime)
    last_updated = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # Resume match score (0–100)
    match_score = Column(Float)
    matched_keywords = Column(Text)   # comma-separated


class Resume(Base):
    __tablename__ = "resumes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    filename = Column(String, nullable=False)
    filepath = Column(String, nullable=False)
    raw_text = Column(Text)
    keywords = Column(Text)           # comma-separated extracted keywords
    is_active = Column(Boolean, default=True)
    uploaded_at = Column(DateTime, default=datetime.datetime.utcnow)


def get_engine(db_path: str = "data/jobs.db"):
    return create_engine(f"sqlite:///{db_path}", echo=False)


def init_db(db_path: str = "data/jobs.db"):
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)
    return engine


def get_session(engine) -> Session:
    return Session(engine)
