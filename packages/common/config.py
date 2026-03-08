"""Application configuration — loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    # ── Database ────────────────────────────────────────────────────────
    database_url: str = field(
        default_factory=lambda: os.environ.get(
            "DATABASE_URL",
            "postgresql+asyncpg://investigator:changeme@localhost:5432/investigator",
        )
    )
    database_url_sync: str = field(
        default_factory=lambda: os.environ.get(
            "DATABASE_URL",
            "postgresql+asyncpg://investigator:changeme@localhost:5432/investigator",
        ).replace("+asyncpg", "+psycopg2")
    )

    # ── Redis ───────────────────────────────────────────────────────────
    redis_url: str = field(
        default_factory=lambda: os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    )

    # ── Neo4j ───────────────────────────────────────────────────────────
    neo4j_uri: str = field(
        default_factory=lambda: os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    )
    neo4j_user: str = field(
        default_factory=lambda: os.environ.get("NEO4J_USER", "neo4j")
    )
    neo4j_password: str = field(
        default_factory=lambda: os.environ.get("NEO4J_PASSWORD", "changeme")
    )

    # ── Provider Keys ───────────────────────────────────────────────────
    helius_api_key: str = field(
        default_factory=lambda: os.environ.get("HELIUS_API_KEY", "")
    )
    dexscreener_api_key: str = field(
        default_factory=lambda: os.environ.get("DEXSCREENER_API_KEY", "")
    )
    etherscan_api_key: str = field(
        default_factory=lambda: os.environ.get("ETHERSCAN_API_KEY", "")
    )
    solscan_api_key: str = field(
        default_factory=lambda: os.environ.get("SOLSCAN_API_KEY", "")
    )
    github_token: str = field(
        default_factory=lambda: os.environ.get("GITHUB_TOKEN", "")
    )
    x_bearer_token: str = field(
        default_factory=lambda: os.environ.get("X_BEARER_TOKEN", "")
    )
    x_api_key: str = field(
        default_factory=lambda: os.environ.get("X_API_KEY", "")
    )
    x_api_secret: str = field(
        default_factory=lambda: os.environ.get("X_API_SECRET", "")
    )
    x_access_token: str = field(
        default_factory=lambda: os.environ.get("X_ACCESS_TOKEN", "")
    )
    x_access_token_secret: str = field(
        default_factory=lambda: os.environ.get("X_ACCESS_TOKEN_SECRET", "")
    )
    x_agent_username: str = field(
        default_factory=lambda: os.environ.get("X_AGENT_USERNAME", "")
    )
    bags_api_key: str = field(
        default_factory=lambda: os.environ.get("BAGS_API_KEY", "")
    )
    bags_partner_key: str = field(
        default_factory=lambda: os.environ.get("BAGS_PARTNER_KEY", "")
    )

    # ── LLM ─────────────────────────────────────────────────────────────
    anthropic_api_key: str = field(
        default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", "")
    )
    llm_model: str = field(
        default_factory=lambda: os.environ.get("LLM_MODEL", "claude-sonnet-4-6")
    )

    # ── App ──────────────────────────────────────────────────────────────
    env: str = field(
        default_factory=lambda: os.environ.get("ENV", "development")
    )
    log_level: str = field(
        default_factory=lambda: os.environ.get("LOG_LEVEL", "INFO")
    )
    api_port: int = field(
        default_factory=lambda: int(os.environ.get("API_PORT", "8000"))
    )
    case_max_depth: int = field(
        default_factory=lambda: int(os.environ.get("CASE_MAX_DEPTH", "5"))
    )
    case_budget_limit_usd: float = field(
        default_factory=lambda: float(os.environ.get("CASE_BUDGET_LIMIT_USD", "0.50"))
    )


# Singleton — import this everywhere.
from dotenv import load_dotenv
load_dotenv()
settings = Settings()
