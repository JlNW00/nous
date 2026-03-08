"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Search, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { investigate } from "@/lib/api";
import type { Chain, RecentInvestigation } from "@/lib/types";

const STEPS = [
  "Collecting on-chain data...",
  "Fetching market signals...",
  "Probing infrastructure...",
  "Scoring credibility...",
  "Generating report...",
];

export function InvestigationForm() {
  const router = useRouter();
  const [address, setAddress] = useState("");
  const [loading, setLoading] = useState(false);
  const [step, setStep] = useState(0);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!address.trim()) return;

    setLoading(true);
    setError(null);
    setStep(0);

    const timers = STEPS.map((_, i) =>
      setTimeout(() => setStep(i), i * 2500)
    );

    try {
      const result = await investigate({
        chain: "solana" as Chain,
        token_address: address.trim(),
      });

      // Save to recent
      const recent: RecentInvestigation[] = JSON.parse(
        localStorage.getItem("recent_investigations") || "[]"
      );
      recent.unshift({
        case_id: result.case_id,
        project_name: result.report.project.name,
        symbol: result.report.project.symbol,
        chain: "solana",
        verdict: result.report.verdict,
        score: result.report.credibility_score,
        timestamp: new Date().toISOString(),
      });
      localStorage.setItem(
        "recent_investigations",
        JSON.stringify(recent.slice(0, 20))
      );

      router.push(`/report/${result.case_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Investigation failed");
      setLoading(false);
    } finally {
      timers.forEach(clearTimeout);
    }
  }

  return (
    <div className="w-full max-w-xl space-y-4">
      <form onSubmit={onSubmit} className="flex gap-2">
        <Input
          value={address}
          onChange={(e) => setAddress(e.target.value)}
          placeholder="Enter Solana token address..."
          className="flex-1 h-12 text-base"
          disabled={loading}
        />
        <Button type="submit" size="lg" disabled={loading || !address.trim()}>
          {loading ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Search className="h-4 w-4" />
          )}
          <span className="ml-2">{loading ? "Investigating..." : "Investigate"}</span>
        </Button>
      </form>

      {loading && (
        <div className="rounded-lg border border-border/50 bg-card p-6 space-y-3">
          {STEPS.map((text, i) => (
            <div
              key={text}
              className={`flex items-center gap-3 text-sm transition-opacity duration-500 ${
                i <= step ? "opacity-100" : "opacity-20"
              }`}
            >
              {i < step ? (
                <div className="h-2 w-2 rounded-full bg-emerald-400" />
              ) : i === step ? (
                <Loader2 className="h-3 w-3 animate-spin text-primary" />
              ) : (
                <div className="h-2 w-2 rounded-full bg-muted-foreground/30" />
              )}
              <span>{text}</span>
            </div>
          ))}
        </div>
      )}

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
    </div>
  );
}
