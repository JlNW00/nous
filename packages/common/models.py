"""SQLAlchemy ORM models — mirrors docs/schema.sql exactly."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# ── Core Tables ─────────────────────────────────────────────────────────────


class Project(Base):
    __tablename__ = "projects"

    project_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    canonical_name = Column(Text, nullable=False)
    symbol = Column(Text)
    chain = Column(Text, nullable=False)
    primary_contract = Column(Text)
    primary_domain = Column(Text)
    status = Column(Text, nullable=False, default="active")
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    aliases = relationship("ProjectAlias", back_populates="project", cascade="all, delete-orphan")
    cases = relationship("Case", back_populates="project", cascade="all, delete-orphan")
    links = relationship("ProjectLink", back_populates="project", cascade="all, delete-orphan")


class ProjectAlias(Base):
    __tablename__ = "project_aliases"
    __table_args__ = (UniqueConstraint("project_id", "alias_type", "alias_value"),)

    alias_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False)
    alias_type = Column(Text, nullable=False)
    alias_value = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    project = relationship("Project", back_populates="aliases")


class Case(Base):
    __tablename__ = "cases"

    case_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False)
    trigger_source = Column(Text, nullable=False)
    priority = Column(Text, nullable=False, default="medium")
    status = Column(Text, nullable=False, default="created")
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="cases")
    evidence = relationship("RawEvidence", back_populates="case", cascade="all, delete-orphan")
    signals = relationship("Signal", back_populates="case", cascade="all, delete-orphan")
    reports = relationship("Report", back_populates="case", cascade="all, delete-orphan")
    annotations = relationship("AnalystAnnotation", back_populates="case", cascade="all, delete-orphan")
    jobs = relationship("Job", back_populates="case")


class Wallet(Base):
    __tablename__ = "wallets"
    __table_args__ = (UniqueConstraint("chain", "address"),)

    wallet_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chain = Column(Text, nullable=False)
    address = Column(Text, nullable=False)
    first_seen_at = Column(DateTime(timezone=True))
    label = Column(Text)
    risk_label = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class Contract(Base):
    __tablename__ = "contracts"
    __table_args__ = (UniqueConstraint("chain", "address"),)

    contract_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chain = Column(Text, nullable=False)
    address = Column(Text, nullable=False)
    contract_type = Column(Text)
    deploy_tx = Column(Text)
    deployer_wallet_id = Column(UUID(as_uuid=True), ForeignKey("wallets.wallet_id"))
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class Domain(Base):
    __tablename__ = "domains"

    domain_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    domain = Column(Text, nullable=False, unique=True)
    first_seen_at = Column(DateTime(timezone=True))
    registrar = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class Repo(Base):
    __tablename__ = "repos"

    repo_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider = Column(Text, nullable=False, default="github")
    repo_url = Column(Text, nullable=False, unique=True)
    owner_name = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class SocialAccount(Base):
    __tablename__ = "social_accounts"
    __table_args__ = (UniqueConstraint("platform", "handle"),)

    account_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    platform = Column(Text, nullable=False)
    handle = Column(Text, nullable=False)
    profile_url = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class RawEvidence(Base):
    __tablename__ = "raw_evidence"
    __table_args__ = (UniqueConstraint("case_id", "hash"),)

    evidence_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("cases.case_id", ondelete="CASCADE"), nullable=False)
    source_type = Column(Text, nullable=False)
    provider = Column(Text, nullable=False)
    fetched_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    payload_json = Column(JSONB, nullable=False)
    hash = Column(Text, nullable=False)

    case = relationship("Case", back_populates="evidence")


class Signal(Base):
    __tablename__ = "signals"

    signal_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("cases.case_id", ondelete="CASCADE"), nullable=False)
    signal_name = Column(Text, nullable=False)
    signal_value = Column(Float)
    score_component = Column(Text)
    confidence = Column(Float, nullable=False, default=0.5)
    evidence_refs = Column(ARRAY(UUID(as_uuid=True)), nullable=False, default=[])
    calculated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    case = relationship("Case", back_populates="signals")


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (UniqueConstraint("case_id", "version"),)

    report_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("cases.case_id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    verdict = Column(Text)
    credibility_score = Column(Float)
    confidence = Column(Float)
    report_json = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    case = relationship("Case", back_populates="reports")
    score_history = relationship("ScoreHistory", back_populates="report", cascade="all, delete-orphan")


class EntityCluster(Base):
    __tablename__ = "entity_clusters"

    entity_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cluster_label = Column(Text)
    cluster_score = Column(Float)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


# ── Helper Tables ───────────────────────────────────────────────────────────


class ProjectLink(Base):
    __tablename__ = "project_links"
    __table_args__ = (UniqueConstraint("project_id", "linked_object_type", "linked_object_id", "relation_type"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False)
    linked_object_type = Column(Text, nullable=False)
    linked_object_id = Column(UUID(as_uuid=True), nullable=False)
    relation_type = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    project = relationship("Project", back_populates="links")


class ProviderCache(Base):
    __tablename__ = "provider_cache"

    cache_key = Column(Text, primary_key=True)
    provider = Column(Text, nullable=False)
    payload_json = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime(timezone=True), nullable=False)


class Job(Base):
    __tablename__ = "jobs"

    job_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_type = Column(Text, nullable=False)
    case_id = Column(UUID(as_uuid=True), ForeignKey("cases.case_id", ondelete="SET NULL"))
    status = Column(Text, nullable=False, default="pending")
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    error_message = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    case = relationship("Case", back_populates="jobs")


class AnalystAnnotation(Base):
    __tablename__ = "analyst_annotations"

    annotation_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("cases.case_id", ondelete="CASCADE"), nullable=False)
    author = Column(Text, nullable=False)
    note = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    case = relationship("Case", back_populates="annotations")


class ScoreHistory(Base):
    __tablename__ = "score_history"

    history_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_id = Column(UUID(as_uuid=True), ForeignKey("reports.report_id", ondelete="CASCADE"), nullable=False)
    score_name = Column(Text, nullable=False)
    score_value = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    report = relationship("Report", back_populates="score_history")
