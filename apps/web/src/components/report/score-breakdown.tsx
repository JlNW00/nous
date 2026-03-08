"use client";

import { CATEGORY_LABELS, scoreColor } from "@/lib/constants";
import type { ScoreBreakdownItem } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface ScoreBreakdownProps {
  categories: ScoreBreakdownItem[];
}

export function ScoreBreakdown({ categories }: ScoreBreakdownProps) {
  if (!categories || categories.length === 0) return null;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">Score Breakdown</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {categories.map((cat) => {
          const pct = cat.max > 0 ? (cat.earned / cat.max) * 100 : 0;
          const color = scoreColor(pct);
          const label = CATEGORY_LABELS[cat.category] || cat.category;

          return (
            <div key={cat.category} className="space-y-1">
              <div className="flex items-center justify-between text-sm">
                <span>{label}</span>
                <span className="font-mono text-xs text-muted-foreground">
                  {cat.earned.toFixed(1)} / {cat.max}
                </span>
              </div>
              <div className="h-2 rounded-full bg-muted overflow-hidden">
                <div
                  className="h-full rounded-full transition-all duration-700 ease-out"
                  style={{ width: `${pct}%`, backgroundColor: color }}
                />
              </div>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}
