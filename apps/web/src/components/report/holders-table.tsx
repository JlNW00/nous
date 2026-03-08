"use client";

import type { HolderInfo } from "@/lib/types";
import { Card, CardContent } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ExternalLink } from "lucide-react";

interface HoldersTableProps {
  holders: HolderInfo[];
}

export function HoldersTable({ holders }: HoldersTableProps) {
  if (!holders || holders.length === 0) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-muted-foreground text-sm">
          No holder data available.
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardContent className="p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-8">#</TableHead>
              <TableHead>Address</TableHead>
              <TableHead className="text-right">Percentage</TableHead>
              <TableHead className="text-right">Amount</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {holders.map((h, i) => (
              <TableRow key={h.address}>
                <TableCell className="text-muted-foreground text-xs">{i + 1}</TableCell>
                <TableCell>
                  <a
                    href={`https://solscan.io/account/${h.address}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="font-mono text-xs text-primary hover:underline flex items-center gap-1"
                  >
                    {h.address.slice(0, 8)}...{h.address.slice(-6)}
                    <ExternalLink className="h-2.5 w-2.5" />
                  </a>
                </TableCell>
                <TableCell className="text-right">
                  <div className="flex items-center justify-end gap-2">
                    <div className="w-16 h-1.5 rounded-full bg-muted overflow-hidden">
                      <div
                        className="h-full rounded-full bg-primary/60"
                        style={{ width: `${Math.min(h.percentage, 100)}%` }}
                      />
                    </div>
                    <span className="font-mono text-xs w-14 text-right">
                      {h.percentage.toFixed(2)}%
                    </span>
                  </div>
                </TableCell>
                <TableCell className="text-right font-mono text-xs">
                  {formatAmount(h.amount)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

function formatAmount(n: number): string {
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(2)}B`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toFixed(2);
}
