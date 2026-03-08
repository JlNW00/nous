"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { getReport } from "@/lib/api";
import type { ReportResponse, ReportJson, Verdict } from "@/lib/types";
import { VERDICT_CONFIG, CATEGORY_LABELS, SIGNAL_LABELS, scoreColor } from "@/lib/constants";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import { ScoreRing } from "@/components/report/score-ring";
import { ScoreBreakdown } from "@/components/report/score-breakdown";
import { SignalTable } from "@/components/report/signal-table";
import { FundingChain } from "@/components/report/funding-chain";
import { HoldersTable } from "@/components/report/holders-table";
import {
  AlertTriangle,
  ExternalLink,
  GitBranch,
  Globe,
  Copy,
  Check,
} from "lucide-react";

export default function ReportPage() {
  const params = useParams();
  const caseId = params.caseId as string;
  const [data, setData] = useState<ReportResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    getReport(caseId)
      .then(setData)
      .catch((e) => setError(e.message));
  }, [caseId]);

  if (error) {
    return (
      <div className="max-w-4xl mx-auto px-4 py-20 text-center">
        <AlertTriangle className="h-12 w-12 text-destructive mx-auto mb-4" />
        <h2 className="text-xl font-semibold mb-2">Report Not Found</h2>
        <p className="text-muted-foreground">{error}</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="max-w-4xl mx-auto px-4 py-12 space-y-6">
        <Skeleton className="h-8 w-64" />
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Skeleton className="h-48" />
          <Skeleton className="h-48 md:col-span-2" />
        </div>
        <Skeleton className="h-64" />
      </div>
    );
  }

  const report = data.report_json;
  const verdict = report.verdict;
  const vc = VERDICT_CONFIG[verdict];

  function copyContract() {
    if (report.project?.primary_contract) {
      navigator.clipboard.writeText(report.project.primary_contract);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }

  return (
    <div className="max-w-5xl mx-auto px-4 py-8 space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center gap-4">
        <div className="flex items-center gap-4 flex-1 min-w-0">
          {report.project?.image && (
            <img
              src={report.project.image}
              alt={report.project.name}
              className="h-12 w-12 rounded-full ring-2 ring-border"
            />
          )}
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h1 className="text-2xl font-bold truncate">{report.project?.name || "Unknown"}</h1>
              {report.project?.symbol && (
                <span className="text-lg text-muted-foreground">({report.project.symbol})</span>
              )}
              <Badge variant="outline" className={`${vc.bg} ${vc.color} border`}>
                {vc.label}
              </Badge>
            </div>
            {report.project?.primary_contract && (
              <button
                onClick={copyContract}
                className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground mt-1 font-mono transition-colors"
              >
                {report.project.primary_contract.slice(0, 8)}...{report.project.primary_contract.slice(-6)}
                {copied ? <Check className="h-3 w-3 text-emerald-400" /> : <Copy className="h-3 w-3" />}
              </button>
            )}
          </div>
        </div>
        <div className="flex items-center gap-3 text-sm text-muted-foreground">
          <span className="capitalize">{report.project?.chain}</span>
          <span>v{data.version}</span>
        </div>
      </div>

      {/* Score + Summary row */}
      <div className="grid grid-cols-1 md:grid-cols-[200px_1fr] gap-4">
        {/* Score ring */}
        <Card className="flex items-center justify-center py-6">
          <CardContent className="flex flex-col items-center gap-2 p-0">
            <ScoreRing score={report.credibility_score} size={120} />
            <span className="text-xs text-muted-foreground mt-1">
              Confidence: {((report.overall_confidence || 0) * 100).toFixed(0)}%
            </span>
          </CardContent>
        </Card>

        {/* Executive summary + findings */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Executive Summary</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm leading-relaxed">{report.executive_summary}</p>
            {report.top_findings && report.top_findings.length > 0 && (
              <div className="space-y-1.5">
                <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Key Findings</span>
                <ul className="space-y-1">
                  {report.top_findings.map((f, i) => (
                    <li key={i} className="text-sm flex items-start gap-2">
                      <span className="text-muted-foreground mt-0.5 shrink-0">&bull;</span>
                      <span>{f}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Score breakdown */}
      <ScoreBreakdown categories={report.score_breakdown} />

      {/* Tabs for detailed data */}
      <Tabs defaultValue="signals">
        <TabsList variant="line" className="w-full justify-start">
          <TabsTrigger value="signals">Signals</TabsTrigger>
          <TabsTrigger value="deployer">Deployer</TabsTrigger>
          <TabsTrigger value="holders">Holders</TabsTrigger>
          <TabsTrigger value="market">Market</TabsTrigger>
          <TabsTrigger value="code">Code & Infra</TabsTrigger>
        </TabsList>

        <TabsContent value="signals" className="pt-4">
          <SignalTable signals={report.signals} />
        </TabsContent>

        <TabsContent value="deployer" className="pt-4">
          <DeployerSection deployer={report.deployer} />
        </TabsContent>

        <TabsContent value="holders" className="pt-4">
          <HoldersTable holders={report.top_holders} />
        </TabsContent>

        <TabsContent value="market" className="pt-4">
          <MarketSection market={report.market_data} />
        </TabsContent>

        <TabsContent value="code" className="pt-4">
          <CodeInfraSection github={report.github} infra={report.infrastructure} />
        </TabsContent>
      </Tabs>

      {/* Open questions & missing data */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {report.open_questions && report.open_questions.length > 0 && (
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">Open Questions</CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="space-y-1.5">
                {report.open_questions.map((q, i) => (
                  <li key={i} className="text-sm flex items-start gap-2">
                    <span className="text-yellow-400 mt-0.5">?</span>
                    <span>{q}</span>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        )}
        {report.missing_data && report.missing_data.length > 0 && (
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">Missing Data</CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="space-y-1.5">
                {report.missing_data.map((m, i) => (
                  <li key={i} className="text-sm flex items-start gap-2">
                    <span className="text-orange-400 mt-0.5">&mdash;</span>
                    <span>{m}</span>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}

/* ── Sub-sections ── */

function DeployerSection({ deployer }: { deployer: ReportJson["deployer"] }) {
  if (!deployer?.address) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-muted-foreground text-sm">
          Deployer address could not be identified.
        </CardContent>
      </Card>
    );
  }
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium text-muted-foreground">Deployer Address</CardTitle>
        </CardHeader>
        <CardContent>
          <a
            href={`https://solscan.io/account/${deployer.address}`}
            target="_blank"
            rel="noopener noreferrer"
            className="font-mono text-sm text-primary hover:underline flex items-center gap-1.5"
          >
            {deployer.address}
            <ExternalLink className="h-3 w-3" />
          </a>
        </CardContent>
      </Card>
      {deployer.funding_chain && deployer.funding_chain.length > 0 && (
        <FundingChain chain={deployer.funding_chain} />
      )}
    </div>
  );
}

function MarketSection({ market }: { market: ReportJson["market_data"] }) {
  if (!market) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-muted-foreground text-sm">
          No market data available.
        </CardContent>
      </Card>
    );
  }

  const items = [
    { label: "Price", value: market.price_usd ? `$${Number(market.price_usd).toFixed(8)}` : "N/A" },
    { label: "Market Cap", value: market.market_cap ? `$${formatNum(market.market_cap)}` : "N/A" },
    { label: "Liquidity", value: market.liquidity_usd ? `$${formatNum(market.liquidity_usd)}` : "N/A" },
    { label: "24h Volume", value: market.volume_24h ? `$${formatNum(market.volume_24h)}` : "N/A" },
    { label: "DEX", value: market.dex || "N/A" },
    { label: "Pairs", value: market.pairs_found?.toString() || "N/A" },
  ];

  return (
    <Card>
      <CardContent className="pt-4">
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
          {items.map((item) => (
            <div key={item.label} className="space-y-1">
              <span className="text-xs text-muted-foreground">{item.label}</span>
              <p className="text-sm font-medium font-mono">{item.value}</p>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function CodeInfraSection({
  github,
  infra,
}: {
  github: ReportJson["github"];
  infra: ReportJson["infrastructure"];
}) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
            <GitBranch className="h-4 w-4" />
            GitHub
          </CardTitle>
        </CardHeader>
        <CardContent>
          {github?.repo?.exists ? (
            <div className="space-y-2 text-sm">
              <a
                href={`https://github.com/${github.repo.owner}/${github.repo.repo}`}
                target="_blank"
                rel="noopener noreferrer"
                className="text-primary hover:underline flex items-center gap-1"
              >
                {github.repo.owner}/{github.repo.repo}
                <ExternalLink className="h-3 w-3" />
              </a>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div>
                  <span className="text-muted-foreground">Age:</span>{" "}
                  <span className="font-medium">{github.repo.age_days}d</span>
                </div>
                <div>
                  <span className="text-muted-foreground">Stars:</span>{" "}
                  <span className="font-medium">{github.repo.stars}</span>
                </div>
                <div>
                  <span className="text-muted-foreground">Commits (28d):</span>{" "}
                  <span className="font-medium">{github.commits_28d ?? "N/A"}</span>
                </div>
                <div>
                  <span className="text-muted-foreground">Authors (28d):</span>{" "}
                  <span className="font-medium">{github.unique_authors_28d ?? "N/A"}</span>
                </div>
              </div>
              {github.repo.is_fork && (
                <Badge variant="outline" className="text-xs bg-yellow-500/10 text-yellow-400 border-yellow-500/30">
                  Forked Repo
                </Badge>
              )}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">No GitHub repository found.</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
            <Globe className="h-4 w-4" />
            Infrastructure
          </CardTitle>
        </CardHeader>
        <CardContent>
          {infra?.domain ? (
            <div className="space-y-2 text-sm">
              <p className="font-mono text-xs">{infra.domain}</p>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div>
                  <span className="text-muted-foreground">DNS:</span>{" "}
                  <StatusDot ok={infra.dns_resolves} />
                </div>
                <div>
                  <span className="text-muted-foreground">HTTPS:</span>{" "}
                  <StatusDot ok={infra.is_https} />
                </div>
                <div>
                  <span className="text-muted-foreground">TLS Valid:</span>{" "}
                  <StatusDot ok={infra.has_valid_tls} />
                </div>
                <div>
                  <span className="text-muted-foreground">Status:</span>{" "}
                  <span className="font-medium">{infra.http_status ?? "N/A"}</span>
                </div>
                {infra.response_time_ms && (
                  <div>
                    <span className="text-muted-foreground">Response:</span>{" "}
                    <span className="font-medium">{infra.response_time_ms}ms</span>
                  </div>
                )}
                {infra.server_header && (
                  <div>
                    <span className="text-muted-foreground">Server:</span>{" "}
                    <span className="font-medium">{infra.server_header}</span>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">No website found to probe.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function StatusDot({ ok }: { ok: boolean | null | undefined }) {
  if (ok === null || ok === undefined) return <span className="text-muted-foreground font-medium">N/A</span>;
  return ok ? (
    <span className="text-emerald-400 font-medium">Yes</span>
  ) : (
    <span className="text-red-400 font-medium">No</span>
  );
}

function formatNum(n: number): string {
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(2)}B`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toFixed(2);
}
