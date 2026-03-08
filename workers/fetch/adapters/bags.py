"""Bags API adapter — §6 of the spec.

Fetches:
- Token launch data (lifetime fees, trading volume, creator earnings)
- Top holders from Bags
- Fee share config
- Partner stats

Bags API docs: https://dev.bags.fm
Base URL: https://public-api-v2.bags.fm/api/v1
Auth: x-api-key header. Rate limit: 1,000 req/hour.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

import httpx

from packages.common.config import settings

logger = logging.getLogger(__name__)

BAGS_BASE = "https://public-api-v2.bags.fm/api/v1"

# Bags program signer — tokens deployed via Bags have this signer in tx history
BAGS_SIGNER = "BAGSB9TpGrZxQbEsrEznv5jXXdwyP6AXerN8aVRiAmcv"


class BagsAdapter:
    """Bags launchpad data via Bags public API v2."""

    def __init__(self) -> None:
        self.api_key = settings.bags_api_key
        if not self.api_key:
            raise ValueError("BAGS_API_KEY not set")
        self.client = httpx.Client(
            timeout=30,
            headers={"x-api-key": self.api_key},
        )

    def close(self) -> None:
        self.client.close()

    # ── Token Data ───────────────────────────────────────────────────

    def get_token_info(self, token_address: str) -> dict[str, Any]:
        """Fetch token data from Bags API (fees, volume, creator earnings)."""
        try:
            response = self.client.get(f"{BAGS_BASE}/token/{token_address}")
            response.raise_for_status()
            data = response.json()
            return {
                "token_address": token_address,
                "name": data.get("name"),
                "symbol": data.get("symbol"),
                "description": data.get("description"),
                "image_url": data.get("imageUrl"),
                "creator": data.get("creator"),
                "created_at": data.get("createdAt"),
                "lifetime_fees_sol": data.get("lifetimeFees", 0),
                "trading_volume_usd": data.get("tradingVolume", 0),
                "market_cap": data.get("marketCap"),
                "holder_count": data.get("holderCount"),
                "bags_launched": True,
                "raw": data,
            }
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                logger.info("Token %s not found on Bags (not Bags-launched)", token_address)
                return {
                    "token_address": token_address,
                    "bags_launched": False,
                    "error": "not_found",
                }
            raise

    def get_token_holders(self, token_address: str, limit: int = 20) -> list[dict[str, Any]]:
        """Fetch top holders for a Bags token."""
        try:
            response = self.client.get(
                f"{BAGS_BASE}/token/{token_address}/holders",
                params={"limit": limit},
            )
            response.raise_for_status()
            data = response.json()
            holders = data if isinstance(data, list) else data.get("holders", [])
            return [
                {
                    "address": h.get("address") or h.get("wallet"),
                    "amount": h.get("amount", 0),
                    "percentage": h.get("percentage", 0),
                }
                for h in holders[:limit]
            ]
        except httpx.HTTPStatusError:
            logger.warning("Failed to fetch Bags holders for %s", token_address)
            return []

    # ── Fee Share Config ─────────────────────────────────────────────

    def get_fee_share_config(self, token_address: str) -> dict[str, Any]:
        """Pull fee share config — who receives fees, what percentage."""
        try:
            response = self.client.get(f"{BAGS_BASE}/token/{token_address}/fees")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError:
            logger.warning("Failed to fetch fee config for %s", token_address)
            return {}

    # ── Partner Stats ────────────────────────────────────────────────

    def get_partner_stats(self) -> dict[str, Any]:
        """Fetch partner fee earnings from Bags."""
        try:
            response = self.client.get(f"{BAGS_BASE}/partner/stats")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError:
            logger.warning("Failed to fetch partner stats")
            return {}

    # ── New Launches (for discovery worker) ──────────────────────────

    def get_recent_launches(self, limit: int = 50) -> list[dict[str, Any]]:
        """Poll Bags API for recently launched tokens."""
        try:
            response = self.client.get(
                f"{BAGS_BASE}/tokens/recent",
                params={"limit": limit, "sort": "createdAt", "order": "desc"},
            )
            response.raise_for_status()
            data = response.json()
            tokens = data if isinstance(data, list) else data.get("tokens", [])
            return [
                {
                    "token_address": t.get("mintAddress") or t.get("tokenAddress") or t.get("address"),
                    "name": t.get("name"),
                    "symbol": t.get("symbol"),
                    "creator": t.get("creator"),
                    "created_at": t.get("createdAt"),
                    "trading_volume_usd": t.get("tradingVolume", 0),
                    "market_cap": t.get("marketCap", 0),
                }
                for t in tokens
            ]
        except httpx.HTTPStatusError:
            logger.warning("Failed to fetch recent Bags launches")
            return []

    # ── Bags Launch Detection (via Helius tx history) ────────────────

    @staticmethod
    def is_bags_launched(helius_creation_tx: dict[str, Any] | None) -> bool:
        """
        Detect whether a token was launched on Bags by checking for the
        Bags program signer in the creation transaction.
        """
        if not helius_creation_tx:
            return False

        # Check Helius enriched format — account keys
        account_keys = []
        if "accountData" in helius_creation_tx:
            for acc in helius_creation_tx.get("accountData", []):
                account_keys.append(acc.get("account", ""))

        # Check instructions for Bags program
        for ix in helius_creation_tx.get("instructions", []):
            if ix.get("programId") == BAGS_SIGNER:
                return True
            for acc in ix.get("accounts", []):
                if acc == BAGS_SIGNER:
                    return True

        # Check top-level account list
        if "transaction" in helius_creation_tx:
            msg = helius_creation_tx["transaction"].get("message", {})
            for key in msg.get("accountKeys", []):
                addr = key.get("pubkey", key) if isinstance(key, dict) else key
                if addr == BAGS_SIGNER:
                    return True

        return BAGS_SIGNER in str(helius_creation_tx)

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def hash_payload(payload: Any) -> str:
        """Deterministic hash for deduplication."""
        raw = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()
