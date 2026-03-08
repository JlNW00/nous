export type Chain = "ethereum" | "solana" | "base" | "arbitrum" | "polygon" | "bsc" | "avalanche" | "other";
export type Verdict = "legitimate" | "suspicious" | "high_risk" | "larp";
export type CaseStatus = "created" | "collecting" | "enriching" | "analyzing" | "scored" | "published" | "failed" | "stale";

export interface InvestigateRequest {
  chain: Chain;
  token_address: string;
}

export interface InvestigateResponse {
  case_id: string;
  project_id: string;
  report: ReportJson;
}

export interface ReportResponse {
  report_id: string;
  case_id: string;
  version: number;
  generated_at: string;
  credibility_score: number | null;
  verdict: Verdict | null;
  confidence: number | null;
  report_json: ReportJson;
  signals: SignalDetail[];
}

export interface SignalDetail {
  signal_name: string;
  signal_value: number | null;
  score_component: string | null;
  confidence: number;
  evidence_refs: string[];
  calculated_at: string;
}

export interface ProjectSummary {
  project_id: string;
  canonical_name: string;
  symbol: string | null;
  chain: Chain;
  primary_contract: string | null;
  aliases: string[];
}

export interface ReportJson {
  executive_summary: string;
  project: ProjectInfo;
  credibility_score: number;
  verdict: Verdict;
  overall_confidence: number;
  score_breakdown: ScoreBreakdownItem[];
  signals: ReportSignal[];
  market_data: MarketData;
  deployer: DeployerInfo;
  top_holders: HolderInfo[];
  missing_data: string[];
  github: GitHubInfo | null;
  infrastructure: InfrastructureInfo | null;
  top_findings: string[];
  open_questions: string[];
}

export interface ProjectInfo {
  name: string;
  symbol: string | null;
  chain: string;
  primary_contract: string | null;
  description: string | null;
  image: string | null;
}

export interface ScoreBreakdownItem {
  category: string;
  earned: number;
  max: number;
  confidence: number;
}

export interface ReportSignal {
  name: string;
  value: number | null;
  confidence: number;
  component: string;
}

export interface MarketData {
  price_usd: string | null;
  market_cap: number | null;
  liquidity_usd: number | null;
  volume_24h: number | null;
  pairs_found: number | null;
  dex: string | null;
  pair_created_at?: number | null;
}

export interface DeployerInfo {
  address: string | null;
  funding_chain: FundingHop[];
}

export interface FundingHop {
  from: string;
  to: string;
  amount_sol: number | null;
  tx_signature: string | null;
}

export interface HolderInfo {
  address: string;
  amount: number;
  percentage: number;
}

export interface GitHubInfo {
  repo: {
    owner: string;
    repo: string;
    exists: boolean;
    age_days: number;
    stars: number;
    is_fork: boolean;
    created_at?: string;
  } | null;
  commits_28d: number | null;
  unique_authors_28d: number | null;
}

export interface InfrastructureInfo {
  domain: string | null;
  dns_resolves: boolean | null;
  http_status: number | null;
  is_https: boolean | null;
  has_valid_tls: boolean | null;
  content_length: number | null;
  server_header: string | null;
  response_time_ms: number | null;
  urls_checked?: string[];
}

export type GraphNodeType = "Contract" | "Wallet" | "Repo" | "Domain";
export type GraphEdgeType = "DEPLOYED" | "FUNDED_BY" | "LINKS_TO";

export interface GraphNode {
  id: string;
  type: GraphNodeType;
  label: string;
  properties: Record<string, unknown>;
}

export interface GraphEdge {
  source: string;
  target: string;
  type: GraphEdgeType;
  properties: Record<string, unknown>;
}

export interface GraphData {
  nodes: GraphNode[];
  links: GraphEdge[];
}

export interface RecentInvestigation {
  case_id: string;
  project_name: string;
  symbol: string | null;
  chain: Chain;
  verdict: Verdict;
  score: number;
  timestamp: string;
}
