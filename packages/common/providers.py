"""Base class for all provider adapters with built-in caching."""

from __future__ import annotations

import hashlib
import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from packages.common.models import ProviderCache, RawEvidence
from packages.common.schemas import EvidencePayload

logger = logging.getLogger(__name__)


class ProviderAdapter(ABC):
    """
    Base class for data collection adapters.

    Subclasses implement `_fetch_raw()` with provider-specific logic.
    Caching and evidence storage are handled here.
    """

    provider_name: str = "unknown"
    source_type: str = "unknown"
    default_ttl: timedelta = timedelta(hours=1)

    @abstractmethod
    def _fetch_raw(self, **kwargs: Any) -> dict[str, Any]:
        """Provider-specific fetch logic. Returns raw JSON-serializable payload."""
        ...

    @abstractmethod
    def _normalize(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Transform raw provider response into a normalized schema."""
        ...

    def _cache_key(self, **kwargs: Any) -> str:
        """Deterministic cache key from call parameters."""
        sorted_params = json.dumps(kwargs, sort_keys=True, default=str)
        h = hashlib.sha256(f"{self.provider_name}:{sorted_params}".encode()).hexdigest()[:32]
        return f"{self.provider_name}:{h}"

    @staticmethod
    def _payload_hash(payload: dict[str, Any]) -> str:
        """Content hash for deduplication in raw_evidence."""
        raw = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()

    def fetch(self, db: Session, **kwargs: Any) -> EvidencePayload:
        """
        Fetch data with cache-through pattern.

        1. Check provider_cache for unexpired entry.
        2. On miss, call _fetch_raw() and store in cache.
        3. Normalize and return.
        """
        key = self._cache_key(**kwargs)
        now = datetime.now(timezone.utc)

        # ── Cache lookup ────────────────────────────────────────────────
        cached = db.execute(
            select(ProviderCache).where(
                ProviderCache.cache_key == key,
                ProviderCache.expires_at > now,
            )
        ).scalar_one_or_none()

        if cached is not None:
            logger.debug("Cache hit for %s", key)
            normalized = self._normalize(cached.payload_json)
            return EvidencePayload(
                source_type=self.source_type,
                provider=self.provider_name,
                payload=normalized,
                raw_hash=self._payload_hash(cached.payload_json),
            )

        # ── Cache miss — fetch from provider ────────────────────────────
        logger.info("Cache miss for %s — fetching from %s", key, self.provider_name)
        raw = self._fetch_raw(**kwargs)

        # Store in cache (upsert)
        db.merge(
            ProviderCache(
                cache_key=key,
                provider=self.provider_name,
                payload_json=raw,
                created_at=now,
                expires_at=now + self.default_ttl,
            )
        )
        db.flush()

        normalized = self._normalize(raw)
        return EvidencePayload(
            source_type=self.source_type,
            provider=self.provider_name,
            payload=normalized,
            raw_hash=self._payload_hash(raw),
        )

    def store_evidence(self, db: Session, case_id: Any, payload: EvidencePayload) -> RawEvidence:
        """Persist evidence linked to a case. Deduplicates by hash."""
        existing = db.execute(
            select(RawEvidence).where(
                RawEvidence.case_id == case_id,
                RawEvidence.hash == payload.raw_hash,
            )
        ).scalar_one_or_none()

        if existing is not None:
            logger.debug("Evidence already stored for case %s hash %s", case_id, payload.raw_hash[:12])
            return existing

        evidence = RawEvidence(
            case_id=case_id,
            source_type=payload.source_type,
            provider=payload.provider,
            payload_json=payload.payload,
            hash=payload.raw_hash,
        )
        db.add(evidence)
        db.flush()
        return evidence


def cleanup_expired_cache(db: Session) -> int:
    """Remove expired cache entries. Call periodically from scheduler."""
    now = datetime.now(timezone.utc)
    result = db.execute(
        delete(ProviderCache).where(ProviderCache.expires_at <= now)
    )
    db.flush()
    count = result.rowcount  # type: ignore[union-attr]
    if count:
        logger.info("Cleaned up %d expired cache entries", count)
    return count
