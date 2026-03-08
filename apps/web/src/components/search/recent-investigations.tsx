"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { VERDICT_CONFIG } from "@/lib/constants";
import type { RecentInvestigation } from "@/lib/types";

export function RecentInvestigations() {
  const [items, setItems] = useState<RecentInvestigation[]>([]);

  useEffect(() => {
    const stored = localStorage.getItem("recent_investigations");
    if (stored) setItems(JSON.parse(stored));
  }, []);

  if (items.length === 0) return null;

  return (
    <div className="w-full max-w-xl space-y-3">
      <h3 className="text-sm font-medium text-muted-foreground">Recent Investigations</h3>
      <div className="space-y-2">
        {items.map((item) => {
          const vc = VERDICT_CONFIG[item.verdict];
          return (
            <Link
              key={item.case_id + item.timestamp}
              href={`/report/${item.case_id}`}
              className="flex items-center justify-between p-3 rounded-lg border border-border/50 bg-card hover:bg-accent/50 transition-colors"
            >
              <div className="flex items-center gap-3">
                <span className="font-medium">
                  {item.project_name}
                  {item.symbol && (
                    <span className="text-muted-foreground ml-1">({item.symbol})</span>
                  )}
                </span>
              </div>
              <div className="flex items-center gap-3">
                <span className="text-sm font-mono">{item.score.toFixed(0)}/100</span>
                <Badge variant="outline" className={`${vc.bg} ${vc.color} border`}>
                  {vc.label}
                </Badge>
              </div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
