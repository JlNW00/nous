"""Enums shared across the entire codebase — mirrors the PostgreSQL enum types."""

from __future__ import annotations

import enum


class Chain(str, enum.Enum):
    ETHEREUM = "ethereum"
    SOLANA = "solana"
    BASE = "base"
    ARBITRUM = "arbitrum"
    POLYGON = "polygon"
    BSC = "bsc"
    AVALANCHE = "avalanche"
    OTHER = "other"


class CaseStatus(str, enum.Enum):
    CREATED = "created"
    COLLECTING = "collecting"
    ENRICHING = "enriching"
    ANALYZING = "analyzing"
    SCORED = "scored"
    PUBLISHED = "published"
    FAILED = "failed"
    STALE = "stale"


class CasePriority(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Verdict(str, enum.Enum):
    LEGITIMATE = "legitimate"
    SUSPICIOUS = "suspicious"
    HIGH_RISK = "high_risk"
    LARP = "larp"


class AliasType(str, enum.Enum):
    CONTRACT = "contract"
    SYMBOL = "symbol"
    NAME = "name"
    DOMAIN = "domain"
    HANDLE = "handle"
    REPO_URL = "repo_url"


class ContractType(str, enum.Enum):
    TOKEN = "token"
    PAIR = "pair"
    FACTORY = "factory"
    PROXY = "proxy"
    MULTISIG = "multisig"
    OTHER = "other"


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


class TriggerSource(str, enum.Enum):
    CHAIN_EVENT = "chain_event"
    TRENDING_FEED = "trending_feed"
    SOCIAL_MENTION = "social_mention"
    MANUAL = "manual"
    RELATED_DISCOVERY = "related_discovery"


class LinkedObjectType(str, enum.Enum):
    WALLET = "wallet"
    CONTRACT = "contract"
    DOMAIN = "domain"
    REPO = "repo"
    SOCIAL_ACCOUNT = "social_account"
    ENTITY_CLUSTER = "entity_cluster"


class RelationType(str, enum.Enum):
    DEPLOYED_BY = "deployed_by"
    FUNDED_BY = "funded_by"
    OFFICIAL_DOMAIN = "official_domain"
    OFFICIAL_REPO = "official_repo"
    OFFICIAL_SOCIAL = "official_social"
    CONTROLS = "controls"
    LINKED_TO = "linked_to"


class SourceType(str, enum.Enum):
    ON_CHAIN = "on_chain"
    MARKET = "market"
    CODE = "code"
    SOCIAL = "social"
    INFRASTRUCTURE = "infrastructure"
    MANUAL = "manual"


class Platform(str, enum.Enum):
    X = "x"
    TELEGRAM = "telegram"
    DISCORD = "discord"
    GITHUB = "github"
    OTHER = "other"


# ── Neo4j Edge Types (§9) ──────────────────────────────────────────────────

class EdgeType(str, enum.Enum):
    DEPLOYED = "DEPLOYED"
    FUNDED_BY = "FUNDED_BY"
    TRANSFERRED_TO = "TRANSFERRED_TO"
    CONTROLS = "CONTROLS"
    PROVIDES_LIQUIDITY_FOR = "PROVIDES_LIQUIDITY_FOR"
    LINKS_TO = "LINKS_TO"
    MENTIONS = "MENTIONS"


# ── Signal Names (§10) ─────────────────────────────────────────────────────

class SignalName(str, enum.Enum):
    TOP_HOLDER_PCT = "top_holder_pct"
    LP_LOCKED = "lp_locked"
    DEPLOYER_REPUTATION = "deployer_reputation"
    CAPITAL_ORIGIN_SCORE = "capital_origin_score"
    RELATED_RUG_COUNT = "related_rug_count"
    REPO_AGE_DAYS = "repo_age_days"
    COMMIT_VELOCITY = "commit_velocity"
    ACCOUNT_AGE_DAYS = "account_age_days"
    ENGAGEMENT_AUTHENTICITY = "engagement_authenticity"
    BACKEND_PRESENCE = "backend_presence"
    NARRATIVE_CONSISTENCY = "narrative_consistency"
    BAGS_LAUNCHED = "bags_launched"
    BAGS_LIFETIME_FEES = "bags_lifetime_fees"
    BAGS_TRADING_VOLUME = "bags_trading_volume"
