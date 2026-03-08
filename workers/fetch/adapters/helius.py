"""Helius provider adapter for Solana on-chain data.

Fetches:
- Token metadata (name, symbol, supply, decimals)
- Top holders
- Transaction history for deployer identification
- Funding source tracing

Helius API docs: https://docs.helius.dev/
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import timedelta
from typing import Any

import httpx

from packages.common.config import settings

logger = logging.getLogger(__name__)

HELIUS_BASE = "https://api.helius.xyz/v0"
HELIUS_RPC = "https://mainnet.helius-rpc.com"


class HeliusAdapter:
    """Solana on-chain data via Helius API."""

    def __init__(self) -> None:
        self.api_key = settings.helius_api_key
        if not self.api_key:
            raise ValueError("HELIUS_API_KEY not set")
        self.client = httpx.Client(timeout=30)

    def close(self) -> None:
        self.client.close()

    # ── Token Metadata ──────────────────────────────────────────────────

    def get_token_metadata(self, mint_address: str) -> dict[str, Any]:
        """Fetch token metadata via Helius DAS API."""
        response = self.client.post(
            f"{HELIUS_RPC}/?api-key={self.api_key}",
            json={
                "jsonrpc": "2.0",
                "id": "get-asset",
                "method": "getAsset",
                "params": {"id": mint_address},
            },
        )
        response.raise_for_status()
        data = response.json()

        if "error" in data:
            logger.warning("Helius getAsset error for %s: %s", mint_address, data["error"])
            return {"error": data["error"], "mint": mint_address}

        result = data.get("result", {})
        content = result.get("content", {})
        metadata = content.get("metadata", {})
        token_info = result.get("token_info", {})

        return {
            "mint": mint_address,
            "name": metadata.get("name"),
            "symbol": metadata.get("symbol"),
            "description": metadata.get("description"),
            "decimals": token_info.get("decimals"),
            "supply": token_info.get("supply"),
            "token_program": token_info.get("token_program"),
            "authorities": result.get("authorities", []),
            "ownership": result.get("ownership", {}),
            "creators": result.get("creators", []),
            "image_url": content.get("links", {}).get("image"),
            "external_url": content.get("links", {}).get("external_url"),
            "raw": result,
        }

    # ── Top Holders ─────────────────────────────────────────────────────

    def get_top_holders(self, mint_address: str, limit: int = 20) -> list[dict[str, Any]]:
        """Fetch largest token holders via RPC getTokenLargestAccounts."""
        response = self.client.post(
            f"{HELIUS_RPC}/?api-key={self.api_key}",
            json={
                "jsonrpc": "2.0",
                "id": "holders",
                "method": "getTokenLargestAccounts",
                "params": [mint_address],
            },
        )
        response.raise_for_status()
        data = response.json()

        if "error" in data:
            logger.warning("getTokenLargestAccounts error: %s", data["error"])
            return []

        accounts = data.get("result", {}).get("value", [])

        # Get total supply for percentage calc
        supply_resp = self.client.post(
            f"{HELIUS_RPC}/?api-key={self.api_key}",
            json={
                "jsonrpc": "2.0",
                "id": "supply",
                "method": "getTokenSupply",
                "params": [mint_address],
            },
        )
        supply_resp.raise_for_status()
        supply_data = supply_resp.json()
        total_supply = float(
            supply_data.get("result", {}).get("value", {}).get("uiAmount", 1) or 1
        )

        holders = []
        for acct in accounts[:limit]:
            ui_amount = float(acct.get("uiAmount", 0) or 0)
            pct = (ui_amount / total_supply * 100) if total_supply > 0 else 0
            holders.append({
                "address": acct.get("address"),
                "amount": ui_amount,
                "percentage": round(pct, 4),
            })

        return holders

    # ── Transaction History (for deployer identification) ───────────────

    def get_token_creation_tx(self, mint_address: str) -> dict[str, Any] | None:
        """Find the transaction that created/minted this token."""
        response = self.client.get(
            f"{HELIUS_BASE}/addresses/{mint_address}/transactions",
            params={
                "api-key": self.api_key,
                "type": "TOKEN_MINT",
                "limit": 5,
            },
        )
        response.raise_for_status()
        txs = response.json()

        if not txs:
            # Fallback: get earliest transactions
            response = self.client.post(
                f"{HELIUS_RPC}/?api-key={self.api_key}",
                json={
                    "jsonrpc": "2.0",
                    "id": "sigs",
                    "method": "getSignaturesForAddress",
                    "params": [
                        mint_address,
                        {"limit": 10},
                    ],
                },
            )
            response.raise_for_status()
            sigs_data = response.json()
            sigs = sigs_data.get("result", [])

            if not sigs:
                return None

            # Get the oldest transaction (last in list)
            oldest_sig = sigs[-1]["signature"]
            return self._get_parsed_transaction(oldest_sig)

        # Return the earliest mint tx
        return txs[-1] if txs else None

    def get_deployer_address(self, mint_address: str) -> str | None:
        """Identify who deployed/created this token."""
        creation_tx = self.get_token_creation_tx(mint_address)
        if not creation_tx:
            return None

        # Helius enriched format
        if "feePayer" in creation_tx:
            return creation_tx["feePayer"]

        # Raw parsed format
        if "transaction" in creation_tx:
            msg = creation_tx["transaction"].get("message", {})
            account_keys = msg.get("accountKeys", [])
            if account_keys:
                # Fee payer is always the first account
                if isinstance(account_keys[0], dict):
                    return account_keys[0].get("pubkey")
                return account_keys[0]

        return None

    # ── Wallet Transaction History ──────────────────────────────────────

    def get_wallet_transactions(
        self, address: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Fetch parsed transaction history for a wallet."""
        response = self.client.get(
            f"{HELIUS_BASE}/addresses/{address}/transactions",
            params={
                "api-key": self.api_key,
                "limit": limit,
            },
        )
        response.raise_for_status()
        return response.json()

    def trace_funding_source(
        self, address: str, max_depth: int = 5
    ) -> list[dict[str, Any]]:
        """
        Trace backwards to find where a wallet's SOL came from.
        Returns a list of funding hops: [{from, to, amount, tx_sig, depth}]
        """
        funding_chain: list[dict[str, Any]] = []
        current_address = address
        visited: set[str] = set()

        for depth in range(max_depth):
            if current_address in visited:
                break
            visited.add(current_address)

            txs = self.get_wallet_transactions(current_address, limit=100)

            # Find the earliest SOL transfer INTO this wallet
            earliest_funding = None
            for tx in reversed(txs):  # Oldest first
                native_transfers = tx.get("nativeTransfers", [])
                for transfer in native_transfers:
                    if (
                        transfer.get("toUserAccount") == current_address
                        and transfer.get("fromUserAccount") != current_address
                        and transfer.get("amount", 0) > 0
                    ):
                        if earliest_funding is None or True:  # Take first found
                            earliest_funding = {
                                "from": transfer["fromUserAccount"],
                                "to": current_address,
                                "amount_sol": transfer["amount"] / 1e9,
                                "tx_signature": tx.get("signature"),
                                "timestamp": tx.get("timestamp"),
                                "depth": depth + 1,
                            }
                            break
                if earliest_funding:
                    break

            if not earliest_funding:
                break

            funding_chain.append(earliest_funding)
            current_address = earliest_funding["from"]

        return funding_chain

    # ── Helpers ──────────────────────────────────────────────────────────

    def _get_parsed_transaction(self, signature: str) -> dict[str, Any] | None:
        """Fetch a single parsed transaction by signature."""
        response = self.client.post(
            f"{HELIUS_RPC}/?api-key={self.api_key}",
            json={
                "jsonrpc": "2.0",
                "id": "tx",
                "method": "getTransaction",
                "params": [
                    signature,
                    {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0},
                ],
            },
        )
        response.raise_for_status()
        data = response.json()
        return data.get("result")

    @staticmethod
    def hash_payload(payload: Any) -> str:
        """Deterministic hash for deduplication."""
        raw = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()
