"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getFeed, type FeedItem } from "@/lib/api";
import { VERDICT_CONFIG, scoreColor } from "@/lib/constants";
import type { Verdict } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Activity, RefreshCw, ExternalLink, Clock } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function FeedPage() {
  const [items, setItems] = useState<FeedItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadFeed() {
    try {
      const data = await getFeed(50);
      setItems(data);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load feed");
    }
  }

  useEffect(() => {
    loadFeed().finally(() => setLoading(false));
  }, []);

  async function refresh() {
    setRefreshing(true);
    await loadFeed();
    setRefreshing(false);
  }

  return (
    <div className="max-w-4xl mx-auto px-4 py-8 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Activity className="h-5 w-5 text-primary" />
          <div>
            <h1 className="text-2xl font-bold">Investigation Feed</h1>
            <p className="text-sm text-muted-foreground">
              Live stream of autonomous investigations
            </p>
          </div>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={refresh}
          disabled={refreshing}
        >
          <RefreshCw className={`h-4 w-4 mr-1.5 ${refreshing ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      {/* Error */}
      {error && (
        <Card className="border-destructive/50">
          <CardContent className="py-4 text-sm text-destructive">{error}</CardContent>
        </Card>
      )}

      {/* Loading */}
      {loading && (
        <div className="space-y-3">
          {[...Array(5)].map((_, i) => (
            <Skeleton key={i} className="h-24 w-full rounded-xl" />
          ))}
        </div>
      )}

      {/* Empty */}
      {!loading && !error && items.length === 0 && (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
            No investigations yet. Run your first investigation from the{" "}
            <Link href="/" className="text-primary hover:underline">
              home page
            </Link>
            .
          </CardContent>
        </Card>
      )}

      {/* Feed items */}
      {!loading && items.length > 0 && (
        <div className="space-y-3">
          {items.map((item) => (
            <FeedCard key={item.case_id} item={item} />
          ))}
        </div>
      )}
    </div>
  );
}

function FeedCard({ item }: { item: FeedItem }) {
  const verdict = item.verdict as Verdict;
  const vc = VERDICT_CONFIG[verdict] || VERDICT_CONFIG.larp;
  const color = scoreColor(item.credibility_score);

  const timeAgo = getTimeAgo(item.published_at);

  return (
    <Link href={`/report/${item.case_id}`}>
      <Card className="hover:ring-2 hover:ring-primary/20 transition-all cursor-pointer">
        <CardContent className="py-4">
          <div className="flex items-start gap-4">
            {/* Score circle */}
            <div
              className="flex items-center justify-center h-14 w-14 rounded-full border-2 shrink-0"
              style={{ borderColor: color }}
            >
              <span className="text-lg font-bold font-mono" style={{ color }}>
                {item.credibility_score.toFixed(0)}
              </span>
            </div>

            {/* Info */}
            <div className="flex-1 min-w-0 space-y-1.5">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-semibold text-base truncate">
                  {item.project_name}
                </span>
                {item.symbol && (
                  <span className="text-sm text-muted-foreground">({item.symbol})</span>
                )}
                <Badge variant="outline" className={`${vc.bg} ${vc.color} border text-xs`}>
                  {vc.label}
                </Badge>
                {item.bags_launched && (
                  <Badge variant="outline" className="text-xs bg-purple-500/10 text-purple-400 border-purple-500/30">
                    Bags
                  </Badge>
                )}
              </div>

              {/* Findings */}
              {item.top_findings && item.top_findings.length > 0 && (
                <p className="text-sm text-muted-foreground line-clamp-2">
                  {item.top_findings[0]}
                </p>
              )}

              {/* Meta row */}
              <div className="flex items-center gap-3 text-xs text-muted-foreground">
                <span className="capitalize">{item.chain}</span>
                <span>&middot;</span>
                <span className="flex items-center gap-1">
                  <Clock className="h-3 w-3" />
                  {timeAgo}
                </span>
                {item.primary_contract && (
                  <>
                    <span>&middot;</span>
                    <span className="font-mono">
                      {item.primary_contract.slice(0, 6)}...{item.primary_contract.slice(-4)}
                    </span>
                  </>
                )}
              </div>
            </div>

            {/* Bags trade link */}
            {item.bags_trade_url && (
              <a
                href={item.bags_trade_url}
                target="_blank"
                rel="noopener noreferrer"
                onClick={(e) => e.stopPropagation()}
                className="shrink-0 flex items-center gap-1 text-xs text-purple-400 hover:text-purple-300 transition-colors px-2 py-1 rounded border border-purple-500/30 bg-purple-500/10"
              >
                Trade
                <ExternalLink className="h-3 w-3" />
              </a>
            )}
          </div>
        </CardContent>
      </Card>
    </Link>
  );
}

function getTimeAgo(isoDate: string): string {
  const now = Date.now();
  const then = new Date(isoDate).getTime();
  const diffMs = now - then;
  const diffMin = Math.floor(diffMs / 60_000);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDays = Math.floor(diffHr / 24);
  return `${diffDays}d ago`;
}
