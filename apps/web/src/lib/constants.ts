import type { Verdict, GraphNodeType } from "./types";

export const VERDICT_CONFIG: Record<Verdict, { color: string; bg: string; label: string }> = {
  legitimate: { color: "text-emerald-400", bg: "bg-emerald-500/20 border-emerald-500/30", label: "Legitimate" },
  suspicious: { color: "text-yellow-400", bg: "bg-yellow-500/20 border-yellow-500/30", label: "Suspicious" },
  high_risk: { color: "text-orange-400", bg: "bg-orange-500/20 border-orange-500/30", label: "High Risk" },
  larp: { color: "text-red-400", bg: "bg-red-500/20 border-red-500/30", label: "LARP" },
};

export function scoreColor(score: number): string {
  if (score >= 80) return "#10B981";
  if (score >= 60) return "#F59E0B";
  if (score >= 35) return "#F97316";
  return "#EF4444";
}

export const CATEGORY_LABELS: Record<string, string> = {
  wallet_entity_reputation: "Wallet & Entity Reputation",
  token_structure_liquidity: "Token Structure & Liquidity",
  developer_code_authenticity: "Developer & Code Authenticity",
  infrastructure_reality: "Infrastructure Reality",
  social_authenticity: "Social Authenticity",
  capital_lineage_quality: "Capital Lineage Quality",
  cross_signal_consistency: "Cross-Signal Consistency",
};

export const SIGNAL_LABELS: Record<string, string> = {
  top_holder_pct: "Top Holder Concentration",
  lp_locked: "Liquidity Level",
  deployer_reputation: "Deployer Reputation",
  capital_origin_score: "Capital Origin",
  related_rug_count: "Related Rug Count",
  repo_age_days: "Repository Age",
  commit_velocity: "Commit Velocity",
  account_age_days: "Account Age",
  engagement_authenticity: "Engagement Authenticity",
  backend_presence: "Backend Presence",
  narrative_consistency: "Narrative Consistency",
};

export const NODE_COLORS: Record<GraphNodeType, string> = {
  Contract: "#3B82F6",
  Wallet: "#F59E0B",
  Repo: "#10B981",
  Domain: "#8B5CF6",
};
