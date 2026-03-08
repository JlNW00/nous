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
