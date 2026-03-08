import type { InvestigateRequest, InvestigateResponse, ReportResponse } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function getReport(caseId: string): Promise<ReportResponse> {
  const res = await fetch(`${API_BASE}/reports/${caseId}/latest`, {
    next: { revalidate: 60 },
  });
  if (!res.ok) throw new Error(`Report fetch failed: ${res.status}`);
  return res.json();
}

export async function investigate(req: InvestigateRequest): Promise<InvestigateResponse> {
  const res = await fetch(`${API_BASE}/investigate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Investigation failed" }));
    throw new Error(err.detail || "Investigation failed");
  }
  return res.json();
}

export interface FeedItem {
  case_id: string;
  project_name: string;
  symbol: string | null;
  chain: string;
  primary_contract: string | null;
  verdict: string;
  credibility_score: number;
  confidence: number | null;
  version: number;
  published_at: string;
  bags_launched: boolean;
  bags_trade_url: string | null;
  top_findings: string[];
}

export async function getFeed(limit: number = 20): Promise<FeedItem[]> {
  const res = await fetch(`${API_BASE}/feed?limit=${limit}`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`Feed fetch failed: ${res.status}`);
  return res.json();
}
