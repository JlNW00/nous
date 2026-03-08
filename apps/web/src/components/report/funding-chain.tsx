"use client";

import type { FundingHop } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ArrowDown, ExternalLink } from "lucide-react";

interface FundingChainProps {
  chain: FundingHop[];
}

export function FundingChain({ chain }: FundingChainProps) {
  if (!chain || chain.length === 0) return null;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          Funding Chain ({chain.length} hop{chain.length !== 1 ? "s" : ""})
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-1">
          {chain.map((hop, i) => (
            <div key={i}>
              <div className="flex items-center gap-3 py-2 px-3 rounded-lg bg-muted/30">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-muted-foreground">From:</span>
                    <a
                      href={`https://solscan.io/account/${hop.from}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="font-mono text-xs text-primary hover:underline truncate flex items-center gap-1"
                    >
                      {hop.from.slice(0, 8)}...{hop.from.slice(-6)}
                      <ExternalLink className="h-2.5 w-2.5 shrink-0" />
                    </a>
                  </div>
                  <div className="flex items-center gap-2 mt-0.5">
                    <span className="text-xs font-medium text-muted-foreground">To:</span>
                    <span className="font-mono text-xs truncate">
                      {hop.to.slice(0, 8)}...{hop.to.slice(-6)}
                    </span>
                  </div>
                </div>
                {hop.amount_sol !== null && (
                  <span className="text-sm font-mono font-medium shrink-0">
                    {hop.amount_sol.toFixed(4)} SOL
                  </span>
                )}
              </div>
              {i < chain.length - 1 && (
                <div className="flex justify-center py-0.5">
                  <ArrowDown className="h-3.5 w-3.5 text-muted-foreground/50" />
                </div>
              )}
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
