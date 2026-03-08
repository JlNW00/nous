"""Neo4j driver wrapper with connection pooling and typed query helpers."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Generator

from neo4j import GraphDatabase, Session as Neo4jSession

from packages.common.config import settings


class Neo4jClient:
    """Thin wrapper around the Neo4j Python driver."""

    def __init__(self) -> None:
        self._driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )

    def close(self) -> None:
        self._driver.close()

    @contextmanager
    def session(self) -> Generator[Neo4jSession, None, None]:
        with self._driver.session() as s:
            yield s

    # ── Node operations ─────────────────────────────────────────────────

    def upsert_node(self, label: str, identifier: dict[str, Any], properties: dict[str, Any]) -> None:
        """MERGE a node by its identifier keys, then SET additional properties."""
        id_clause = " AND ".join(f"n.{k} = ${k}" for k in identifier)
        set_clause = ", ".join(f"n.{k} = ${k}" for k in properties)
        query = (
            f"MERGE (n:{label} {{{', '.join(f'{k}: ${k}' for k in identifier)}}})"
            + (f" ON CREATE SET {set_clause} ON MATCH SET {set_clause}" if set_clause else "")
        )
        with self.session() as s:
            s.run(query, {**identifier, **properties})

    # ── Edge operations ─────────────────────────────────────────────────

    def upsert_edge(
        self,
        from_label: str,
        from_id: dict[str, Any],
        to_label: str,
        to_id: dict[str, Any],
        edge_type: str,
        properties: dict[str, Any] | None = None,
    ) -> None:
        """MERGE an edge between two nodes, upserting both endpoints."""
        from_match = ", ".join(f"{k}: ${f'from_{k}'}" for k in from_id)
        to_match = ", ".join(f"{k}: ${f'to_{k}'}" for k in to_id)
        params: dict[str, Any] = {}
        params.update({f"from_{k}": v for k, v in from_id.items()})
        params.update({f"to_{k}": v for k, v in to_id.items()})

        edge_props = ""
        if properties:
            edge_props = " SET " + ", ".join(f"r.{k} = $edge_{k}" for k in properties)
            params.update({f"edge_{k}": v for k, v in properties.items()})

        query = (
            f"MERGE (a:{from_label} {{{from_match}}})"
            f" MERGE (b:{to_label} {{{to_match}}})"
            f" MERGE (a)-[r:{edge_type}]->(b)"
            + edge_props
        )
        with self.session() as s:
            s.run(query, params)

    # ── Query helpers ───────────────────────────────────────────────────

    def get_neighbors(self, label: str, identifier: dict[str, Any], depth: int = 1) -> list[dict]:
        """Return nodes within `depth` hops of the identified node."""
        match_clause = " AND ".join(f"n.{k} = ${k}" for k in identifier)
        query = (
            f"MATCH (n:{label}) WHERE {match_clause}"
            f" CALL apoc.neighbors.tohop(n, null, {depth}) YIELD node"
            f" RETURN node"
        )
        with self.session() as s:
            result = s.run(query, identifier)
            return [dict(record["node"]) for record in result]

    def find_capital_lineage(self, address: str, max_depth: int = 5) -> list[dict]:
        """Trace FUNDED_BY edges backwards from a wallet to find capital origin."""
        query = (
            "MATCH path = (target:Wallet {address: $address})"
            "-[:FUNDED_BY*1.." + str(max_depth) + "]->(source)"
            " RETURN [n IN nodes(path) | n.address] AS lineage,"
            " length(path) AS depth"
            " ORDER BY depth"
        )
        with self.session() as s:
            result = s.run(query, {"address": address})
            return [dict(record) for record in result]

    def find_related_launches(self, address: str) -> list[dict]:
        """Find projects that share a deployer or funder within 2 hops."""
        query = (
            "MATCH (w:Wallet {address: $address})"
            "-[:DEPLOYED|FUNDED_BY*1..2]-(other:Wallet)"
            "-[:DEPLOYED]->(c:Contract)"
            " RETURN DISTINCT c.address AS contract, other.address AS via_wallet"
        )
        with self.session() as s:
            result = s.run(query, {"address": address})
            return [dict(record) for record in result]


# Singleton
neo4j_client = Neo4jClient()
