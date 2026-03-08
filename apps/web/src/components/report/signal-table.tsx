"use client";

import { SIGNAL_LABELS, scoreColor } from "@/lib/constants";
import type { ReportSignal } from "@/lib/types";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Card, CardContent } from "@/components/ui/card";

interface SignalTableProps {
  signals: ReportSignal[];
}

export function SignalTable({ signals }: SignalTableProps) {
  if (!signals || signals.length === 0) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-muted-foreground text-sm">
          No signals computed.
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
              <TableHead>Signal</TableHead>
              <TableHead className="text-right">Value</TableHead>
              <TableHead className="text-right">Confidence</TableHead>
              <TableHead>Category</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {signals.map((s) => {
              const label = SIGNAL_LABELS[s.name] || s.name;
              const pct = s.value !== null ? s.value * 100 : null;
              const color = pct !== null ? scoreColor(pct) : undefined;

              return (
                <TableRow key={s.name}>
                  <TableCell className="font-medium text-sm">{label}</TableCell>
                  <TableCell className="text-right">
                    {pct !== null ? (
                      <span className="font-mono text-sm" style={{ color }}>
                        {pct.toFixed(0)}%
                      </span>
                    ) : (
                      <span className="text-muted-foreground text-xs">N/A</span>
                    )}
                  </TableCell>
                  <TableCell className="text-right">
                    <span className="font-mono text-xs text-muted-foreground">
                      {(s.confidence * 100).toFixed(0)}%
                    </span>
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">{s.component}</TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
