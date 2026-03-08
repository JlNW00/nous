"""FastAPI application — all REST endpoints per §15."""

from __future__ import annotations

import logging
import uuid
from typing import Any

import fastapi
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.database import get_db, get_sync_session
from packages.common.enums import CaseStatus, TriggerSource
from packages.common.models import (
    AnalystAnnotation,
    Case,
    EntityCluster,
    Project,
    ProjectAlias,
    Report,
    Signal,
)
from packages.common.schemas import (
    AnalyzeRequest,
    CaseCreatedResponse,
    CaseStatusResponse,
    ManualLabelRequest,
    ProjectSummary,
    ReportResponse,
    SignalDetail,
    TimelineEvent,
)
from packages.common.config import settings

from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Crypto Investigator API",
    version="0.1.0",
    description="Autonomous crypto project investigation platform.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health ──────────────────────────────────────────────────────────────────


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# ── POST /investigate — Full synchronous pipeline ───────────────────────────


@app.post("/investigate")
async def investigate(req: AnalyzeRequest) -> dict[str, Any]:
    """
    Run a full investigation synchronously.
    Fetches data, calculates signals, scores, and returns a complete report.
    No Celery/Redis required.
    """
    from workers.fetch.investigate import run_investigation

    with get_sync_session() as db:
        # Resolve or create project
        project = (
            db.query(Project)
            .filter(Project.primary_contract == (req.token_address or req.contract_address))
            .first()
        )
        if not project:
            project = Project(
                canonical_name=req.project_name or f"unknown-{uuid.uuid4().hex[:8]}",
                chain=req.chain,
                primary_contract=req.token_address or req.contract_address,
                primary_domain=req.domain,
            )
            db.add(project)
            db.flush()

        # Create case
        case = Case(
            project_id=project.project_id,
            trigger_source=TriggerSource.MANUAL.value,
            priority="medium",
            status=CaseStatus.CREATED.value,
        )
        db.add(case)
        db.flush()

        # Run the full pipeline
        try:
            report = run_investigation(db, case, project)
        except Exception as exc:
            logger.exception("Investigation failed for %s", req.token_address)
            case.status = CaseStatus.FAILED.value
            db.commit()
            raise HTTPException(status_code=500, detail=f"Investigation failed: {exc}")

        db.commit()

    return {
        "case_id": str(case.case_id),
        "project_id": str(project.project_id),
        "report": report,
    }


# ── POST /cases/analyze — §15 ──────────────────────────────────────────────


@app.post("/cases/analyze", response_model=CaseCreatedResponse, status_code=201)
async def analyze(req: AnalyzeRequest, db: AsyncSession = Depends(get_db)) -> CaseCreatedResponse:
    """Create or refresh a case from input identifiers."""

    # Resolve or create the project
    project = await _resolve_or_create_project(db, req)

    # Create a new case
    case = Case(
        project_id=project.project_id,
        trigger_source=TriggerSource.MANUAL.value,
        priority="medium",
        status=CaseStatus.CREATED.value,
    )
    db.add(case)
    await db.flush()

    # Dispatch enrichment pipeline via Celery
    from packages.common.celery_app import celery_app
    celery_app.send_task("workers.discovery.start_investigation", args=[str(case.case_id)], queue="discovery")

    return CaseCreatedResponse(
        case_id=case.case_id,
        project_id=project.project_id,
        status=case.status,
    )


# ── GET /cases/{case_id} — §15 ─────────────────────────────────────────────


@app.get("/cases/{case_id}", response_model=CaseStatusResponse)
async def get_case(case_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> CaseStatusResponse:
    result = await db.execute(select(Case).where(Case.case_id == case_id))
    case = result.scalar_one_or_none()
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return CaseStatusResponse(
        case_id=case.case_id,
        project_id=case.project_id,
        status=case.status,
        priority=case.priority,
        created_at=case.created_at,
        updated_at=case.updated_at,
    )


# ── GET /reports/{case_id}/latest — §15 ────────────────────────────────────


@app.get("/reports/{case_id}/latest", response_model=ReportResponse)
async def get_latest_report(case_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> ReportResponse:
    result = await db.execute(
        select(Report)
        .where(Report.case_id == case_id)
        .order_by(Report.version.desc())
        .limit(1)
    )
    report = result.scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="No report found for this case")

    # Fetch signals
    sig_result = await db.execute(select(Signal).where(Signal.case_id == case_id))
    signals = [
        SignalDetail(
            signal_name=s.signal_name,
            signal_value=s.signal_value,
            score_component=s.score_component,
            confidence=s.confidence,
            evidence_refs=s.evidence_refs or [],
            calculated_at=s.calculated_at,
        )
        for s in sig_result.scalars().all()
    ]

    return ReportResponse(
        report_id=report.report_id,
        case_id=report.case_id,
        version=report.version,
        generated_at=report.created_at,
        credibility_score=report.credibility_score,
        verdict=report.verdict,
        confidence=report.confidence,
        report_json=report.report_json,
        signals=signals,
    )


# ── GET /projects/search — §15 ─────────────────────────────────────────────


@app.get("/projects/search", response_model=list[ProjectSummary])
async def search_projects(
    q: str = Query(min_length=1, max_length=200),
    db: AsyncSession = Depends(get_db),
) -> list[ProjectSummary]:
    # Search by canonical name or alias
    result = await db.execute(
        select(Project)
        .outerjoin(ProjectAlias, Project.project_id == ProjectAlias.project_id)
        .where(
            (Project.canonical_name.ilike(f"%{q}%"))
            | (Project.symbol.ilike(f"%{q}%"))
            | (ProjectAlias.alias_value.ilike(f"%{q}%"))
        )
        .distinct()
        .limit(20)
    )
    projects = result.scalars().all()

    summaries: list[ProjectSummary] = []
    for p in projects:
        alias_result = await db.execute(
            select(ProjectAlias.alias_value).where(ProjectAlias.project_id == p.project_id)
        )
        aliases = [a for a in alias_result.scalars().all()]
        summaries.append(
            ProjectSummary(
                project_id=p.project_id,
                canonical_name=p.canonical_name,
                symbol=p.symbol,
                chain=p.chain,
                primary_contract=p.primary_contract,
                aliases=aliases,
            )
        )
    return summaries


# ── GET /entities/{entity_id} — §15 ────────────────────────────────────────


@app.get("/entities/{entity_id}")
async def get_entity(entity_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    result = await db.execute(
        select(EntityCluster).where(EntityCluster.entity_id == entity_id)
    )
    entity = result.scalar_one_or_none()
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")

    return {
        "entity_id": entity.entity_id,
        "cluster_label": entity.cluster_label,
        "cluster_score": entity.cluster_score,
        "created_at": entity.created_at,
        # TODO: Populate linked wallets and projects from graph
        "linked_wallets": [],
        "linked_projects": [],
    }


# ── GET /projects/{project_id}/timeline — §15 ──────────────────────────────


@app.get("/projects/{project_id}/timeline", response_model=list[TimelineEvent])
async def get_timeline(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> list[TimelineEvent]:
    # Get the latest case for this project
    case_result = await db.execute(
        select(Case)
        .where(Case.project_id == project_id)
        .order_by(Case.created_at.desc())
        .limit(1)
    )
    case = case_result.scalar_one_or_none()
    if case is None:
        raise HTTPException(status_code=404, detail="No case found for this project")

    # TODO: Build timeline from raw evidence timestamps, signal events, etc.
    # For now return empty — will be populated when workers are implemented.
    return []


# ── POST /labels/manual — §15 ──────────────────────────────────────────────


@app.post("/labels/manual")
async def add_label(req: ManualLabelRequest, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    # Verify case exists
    case_result = await db.execute(select(Case).where(Case.case_id == req.case_id))
    if case_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Case not found")

    annotation = AnalystAnnotation(
        case_id=req.case_id,
        author=req.author,
        note=req.note,
    )
    db.add(annotation)
    await db.flush()

    return {
        "annotation_id": annotation.annotation_id,
        "case_id": annotation.case_id,
        "author": annotation.author,
        "note": annotation.note,
        "created_at": annotation.created_at,
    }


# ── POST /webhook/helius — Helius mint event webhook ──────────────────────


@app.post("/webhook/helius")
async def helius_webhook(request: fastapi.Request) -> dict[str, str]:
    """
    Receive Helius webhook events for new token mints.
    Dispatches autonomous investigation via discovery worker.
    """
    body = await request.json()

    from packages.common.celery_app import celery_app
    celery_app.send_task(
        "workers.discovery.handle_helius_webhook",
        args=[body],
        queue="discovery",
    )

    return {"status": "accepted"}


# ── GET /feed — Public live agent feed (§15) ─────────────────────────────


@app.get("/feed")
async def get_feed(
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """
    Public live agent feed — real-time stream of auto-investigated tokens.
    Returns most recent investigations with verdict badges.
    """
    result = await db.execute(
        select(Report, Case, Project)
        .join(Case, Report.case_id == Case.case_id)
        .join(Project, Case.project_id == Project.project_id)
        .order_by(Report.created_at.desc())
        .limit(limit)
    )
    rows = result.all()

    feed: list[dict[str, Any]] = []
    for report, case, project in rows:
        report_data = report.report_json or {}
        feed.append({
            "case_id": str(case.case_id),
            "project_id": str(project.project_id),
            "name": project.canonical_name,
            "symbol": project.symbol,
            "chain": project.chain,
            "contract": project.primary_contract,
            "credibility_score": report.credibility_score,
            "verdict": report.verdict,
            "confidence": report.confidence,
            "trigger_source": case.trigger_source,
            "investigated_at": report.created_at.isoformat() if report.created_at else None,
            "top_findings": report_data.get("top_findings", [])[:3],
            "bags_launched": (report_data.get("bags") or {}).get("bags_launched", False),
            "market_cap": (report_data.get("market_data") or {}).get("market_cap"),
            "bags_partner_cta": report_data.get("bags_partner_cta"),
        })

    return feed


# ── GET /partner/stats — Partner fee earnings from Bags (§15) ────────────


@app.get("/partner/stats")
async def get_partner_stats() -> dict[str, Any]:
    """Fetch partner fee earnings from Bags API."""
    if not settings.bags_api_key:
        return {"error": "BAGS_API_KEY not configured", "earnings": {}}

    try:
        from workers.fetch.adapters.bags import BagsAdapter

        bags = BagsAdapter()
        stats = bags.get_partner_stats()
        bags.close()
        return stats
    except Exception as exc:
        logger.warning("Failed to fetch partner stats: %s", exc)
        return {"error": str(exc), "earnings": {}}


# ── Helpers ─────────────────────────────────────────────────────────────────


async def _resolve_or_create_project(db: AsyncSession, req: AnalyzeRequest) -> Project:
    """Find existing project by contract/name or create a new one."""

    # Try to find by contract address first
    if req.token_address or req.contract_address:
        addr = req.token_address or req.contract_address
        result = await db.execute(
            select(Project).where(Project.primary_contract == addr)
        )
        project = result.scalar_one_or_none()
        if project is not None:
            return project

    # Try by name
    if req.project_name:
        result = await db.execute(
            select(Project).where(
                func.lower(Project.canonical_name) == func.lower(req.project_name)
            )
        )
        project = result.scalar_one_or_none()
        if project is not None:
            return project

    # Create new project
    project = Project(
        canonical_name=req.project_name or f"unknown-{uuid.uuid4().hex[:8]}",
        symbol=None,
        chain=req.chain,
        primary_contract=req.token_address or req.contract_address,
        primary_domain=req.domain,
    )
    db.add(project)
    await db.flush()

    # Store aliases for all provided identifiers
    alias_pairs: list[tuple[str, str | None]] = [
        ("contract", req.token_address),
        ("contract", req.contract_address),
        ("name", req.project_name),
        ("domain", req.domain),
        ("repo_url", req.github_repo),
        ("handle", req.x_handle),
    ]
    for alias_type, alias_value in alias_pairs:
        if alias_value:
            db.add(
                ProjectAlias(
                    project_id=project.project_id,
                    alias_type=alias_type,
                    alias_value=alias_value,
                )
            )
    await db.flush()

    return project
