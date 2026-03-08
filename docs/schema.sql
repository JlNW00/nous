-- ============================================================================
-- Crypto Investigator — PostgreSQL Schema
-- Matches spec §8.1 and §8.2 exactly, plus enums and indexes.
-- ============================================================================

BEGIN;

-- ── Enums ──────────────────────────────────────────────────────────────────

CREATE TYPE chain_enum AS ENUM (
    'ethereum', 'solana', 'base', 'arbitrum', 'polygon', 'bsc', 'avalanche', 'other'
);

CREATE TYPE case_status AS ENUM (
    'created', 'collecting', 'enriching', 'analyzing', 'scored', 'published', 'failed', 'stale'
);

CREATE TYPE case_priority AS ENUM (
    'low', 'medium', 'high', 'critical'
);

CREATE TYPE verdict_enum AS ENUM (
    'legitimate', 'suspicious', 'high_risk', 'larp'
);

CREATE TYPE alias_type_enum AS ENUM (
    'contract', 'symbol', 'name', 'domain', 'handle', 'repo_url'
);

CREATE TYPE contract_type_enum AS ENUM (
    'token', 'pair', 'factory', 'proxy', 'multisig', 'other'
);

CREATE TYPE job_status AS ENUM (
    'pending', 'running', 'completed', 'failed', 'retrying'
);

CREATE TYPE trigger_source_enum AS ENUM (
    'chain_event', 'trending_feed', 'social_mention', 'manual', 'related_discovery'
);

CREATE TYPE linked_object_type_enum AS ENUM (
    'wallet', 'contract', 'domain', 'repo', 'social_account', 'entity_cluster'
);

CREATE TYPE relation_type_enum AS ENUM (
    'deployed_by', 'funded_by', 'official_domain', 'official_repo',
    'official_social', 'controls', 'linked_to'
);

CREATE TYPE source_type_enum AS ENUM (
    'on_chain', 'market', 'code', 'social', 'infrastructure', 'manual'
);

CREATE TYPE platform_enum AS ENUM (
    'x', 'telegram', 'discord', 'github', 'other'
);

-- ── Extensions ─────────────────────────────────────────────────────────────

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";   -- for fuzzy text search on aliases

-- ── Core Tables (§8.1) ────────────────────────────────────────────────────

CREATE TABLE projects (
    project_id      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    canonical_name  TEXT NOT NULL,
    symbol          TEXT,
    chain           chain_enum NOT NULL,
    primary_contract TEXT,
    primary_domain  TEXT,
    status          TEXT NOT NULL DEFAULT 'active',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE project_aliases (
    alias_id    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id  UUID NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    alias_type  alias_type_enum NOT NULL,
    alias_value TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, alias_type, alias_value)
);

CREATE TABLE cases (
    case_id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id      UUID NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    trigger_source  trigger_source_enum NOT NULL,
    priority        case_priority NOT NULL DEFAULT 'medium',
    status          case_status NOT NULL DEFAULT 'created',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE wallets (
    wallet_id       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    chain           chain_enum NOT NULL,
    address         TEXT NOT NULL,
    first_seen_at   TIMESTAMPTZ,
    label           TEXT,
    risk_label      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (chain, address)
);

CREATE TABLE contracts (
    contract_id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    chain               chain_enum NOT NULL,
    address             TEXT NOT NULL,
    contract_type       contract_type_enum,
    deploy_tx           TEXT,
    deployer_wallet_id  UUID REFERENCES wallets(wallet_id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (chain, address)
);

CREATE TABLE domains (
    domain_id       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    domain          TEXT NOT NULL UNIQUE,
    first_seen_at   TIMESTAMPTZ,
    registrar       TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE repos (
    repo_id     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    provider    TEXT NOT NULL DEFAULT 'github',
    repo_url    TEXT NOT NULL UNIQUE,
    owner_name  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE social_accounts (
    account_id  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    platform    platform_enum NOT NULL,
    handle      TEXT NOT NULL,
    profile_url TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (platform, handle)
);

CREATE TABLE raw_evidence (
    evidence_id     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_id         UUID NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
    source_type     source_type_enum NOT NULL,
    provider        TEXT NOT NULL,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    payload_json    JSONB NOT NULL,
    hash            TEXT NOT NULL,
    UNIQUE (case_id, hash)
);

CREATE TABLE signals (
    signal_id       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_id         UUID NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
    signal_name     TEXT NOT NULL,
    signal_value    DOUBLE PRECISION,
    score_component TEXT,
    confidence      DOUBLE PRECISION NOT NULL DEFAULT 0.5 CHECK (confidence >= 0 AND confidence <= 1),
    evidence_refs   UUID[] NOT NULL DEFAULT '{}',
    calculated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE reports (
    report_id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_id             UUID NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
    version             INTEGER NOT NULL DEFAULT 1,
    verdict             verdict_enum,
    credibility_score   DOUBLE PRECISION CHECK (credibility_score >= 0 AND credibility_score <= 100),
    confidence          DOUBLE PRECISION CHECK (confidence >= 0 AND confidence <= 1),
    report_json         JSONB NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (case_id, version)
);

CREATE TABLE entity_clusters (
    entity_id       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    cluster_label   TEXT,
    cluster_score   DOUBLE PRECISION,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Helper Tables (§8.2) ──────────────────────────────────────────────────

CREATE TABLE project_links (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id          UUID NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    linked_object_type  linked_object_type_enum NOT NULL,
    linked_object_id    UUID NOT NULL,
    relation_type       relation_type_enum NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, linked_object_type, linked_object_id, relation_type)
);

CREATE TABLE provider_cache (
    cache_key   TEXT PRIMARY KEY,
    provider    TEXT NOT NULL,
    payload_json JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL
);

CREATE TABLE jobs (
    job_id      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_type    TEXT NOT NULL,
    case_id     UUID REFERENCES cases(case_id) ON DELETE SET NULL,
    status      job_status NOT NULL DEFAULT 'pending',
    attempts    INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    error_message TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE analyst_annotations (
    annotation_id   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_id         UUID NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
    author          TEXT NOT NULL,
    note            TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE score_history (
    history_id  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    report_id   UUID NOT NULL REFERENCES reports(report_id) ON DELETE CASCADE,
    score_name  TEXT NOT NULL,
    score_value DOUBLE PRECISION NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Indexes ────────────────────────────────────────────────────────────────

CREATE INDEX idx_project_aliases_value ON project_aliases USING gin (alias_value gin_trgm_ops);
CREATE INDEX idx_cases_project_id ON cases (project_id);
CREATE INDEX idx_cases_status ON cases (status);
CREATE INDEX idx_wallets_address ON wallets (address);
CREATE INDEX idx_contracts_address ON contracts (address);
CREATE INDEX idx_contracts_deployer ON contracts (deployer_wallet_id);
CREATE INDEX idx_raw_evidence_case_id ON raw_evidence (case_id);
CREATE INDEX idx_signals_case_id ON signals (case_id);
CREATE INDEX idx_signals_name ON signals (signal_name);
CREATE INDEX idx_reports_case_id ON reports (case_id);
CREATE INDEX idx_jobs_case_id ON jobs (case_id);
CREATE INDEX idx_jobs_status ON jobs (status);
CREATE INDEX idx_provider_cache_expires ON provider_cache (expires_at);
CREATE INDEX idx_score_history_report ON score_history (report_id);
CREATE INDEX idx_project_links_project ON project_links (project_id);

-- ── Updated-at trigger ─────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_projects_updated_at
    BEFORE UPDATE ON projects FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trg_cases_updated_at
    BEFORE UPDATE ON cases FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trg_entity_clusters_updated_at
    BEFORE UPDATE ON entity_clusters FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trg_jobs_updated_at
    BEFORE UPDATE ON jobs FOR EACH ROW EXECUTE FUNCTION update_updated_at();

COMMIT;
