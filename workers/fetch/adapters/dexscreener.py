"""DexScreener adapter for market and liquidity data.

No API key required — DexScreener's API is public.
Rate limit: ~300 requests/min.

Docs: https://docs.dexscreener.com/api/reference
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEXSCREENER_BASE = "https://api.dexscreener.com/latest"


class DexScreenerAdapter:
    """Market data from DexScreener."""

    def __init__(self) -> None:
        self.client = httpx.Client(timeout=20)

    def close(self) -> None:
        self.client.close()

    def get_token_pairs(self, token_address: str) -> list[dict[str, Any]]:
        """Fetch all trading pairs for a token across all DEXes."""
        response = self.client.get(
            f"{DEXSCREENER_BASE}/dex/tokens/{token_address}"
        )
        response.raise_for_status()
        data = response.json()
        return data.get("pairs", []) or []

    def get_pair_by_address(self, pair_address: str, chain: str = "solana") -> dict[str, Any] | None:
        """Fetch a specific DEX pair by its address."""
        response = self.client.get(
            f"{DEXSCREENER_BASE}/dex/pairs/{chain}/{pair_address}"
        )
        response.raise_for_status()
        data = response.json()
        pairs = data.get("pairs", [])
        return pairs[0] if pairs else None

    def get_market_summary(self, token_address: str) -> dict[str, Any]:
        """Build a normalized market summary from DexScreener data."""
        pairs = self.get_token_pairs(token_address)

        if not pairs:
            return {
                "token_address": token_address,
                "pairs_found": 0,
                "error": "no_pairs_found",
            }

        # Sort by liquidity (highest first)
        pairs_sorted = sorted(
            pairs,
            key=lambda p: float(p.get("liquidity", {}).get("usd", 0) or 0),
            reverse=True,
        )

        primary_pair = pairs_sorted[0]
        base_token = primary_pair.get("baseToken", {})
        quote_token = primary_pair.get("quoteToken", {})

        # Aggregate liquidity across all pairs
        total_liquidity_usd = sum(
            float(p.get("liquidity", {}).get("usd", 0) or 0)
            for p in pairs
        )
        total_volume_24h = sum(
            float(p.get("volume", {}).get("h24", 0) or 0)
            for p in pairs
        )

        return {
            "token_address": token_address,
            "pairs_found": len(pairs),
            "name": base_token.get("name"),
            "symbol": base_token.get("symbol"),
            "price_usd": primary_pair.get("priceUsd"),
            "price_native": primary_pair.get("priceNative"),
            "market_cap": primary_pair.get("marketCap"),
            "fdv": primary_pair.get("fdv"),
            "total_liquidity_usd": round(total_liquidity_usd, 2),
            "total_volume_24h": round(total_volume_24h, 2),
            "pair_created_at": primary_pair.get("pairCreatedAt"),
            "dex": primary_pair.get("dexId"),
            "price_change": {
                "5m": primary_pair.get("priceChange", {}).get("m5"),
                "1h": primary_pair.get("priceChange", {}).get("h1"),
                "6h": primary_pair.get("priceChange", {}).get("h6"),
                "24h": primary_pair.get("priceChange", {}).get("h24"),
            },
            "txns_24h": primary_pair.get("txns", {}).get("h24", {}),
            "liquidity": {
                "usd": float(primary_pair.get("liquidity", {}).get("usd", 0) or 0),
                "base": float(primary_pair.get("liquidity", {}).get("base", 0) or 0),
                "quote": float(primary_pair.get("liquidity", {}).get("quote", 0) or 0),
                "locked": False,  # DexScreener doesn't provide lock info directly
            },
            "websites": primary_pair.get("info", {}).get("websites", []),
            "socials": primary_pair.get("info", {}).get("socials", []),
            "all_pairs": [
                {
                    "pair_address": p.get("pairAddress"),
                    "dex": p.get("dexId"),
                    "liquidity_usd": float(p.get("liquidity", {}).get("usd", 0) or 0),
                    "volume_24h": float(p.get("volume", {}).get("h24", 0) or 0),
                }
                for p in pairs_sorted[:10]
            ],
        }

    @staticmethod
    def hash_payload(payload: Any) -> str:
        raw = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()
