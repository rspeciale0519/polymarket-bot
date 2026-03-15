"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { useBotMode } from "@/stores/bot-mode";
import { usePolling } from "@/hooks/use-polling";
import type { PaperMilestoneData } from "@/types/bot";
import { Trophy } from "lucide-react";

async function fetchMilestone(): Promise<PaperMilestoneData | null> {
  try {
    const res = await fetch("/api/settings");
    if (!res.ok) return null;
    const json = await res.json();
    const s = json.data;
    return {
      targetDays: s.paperMilestoneDays ?? 30,
      profitableDays: 0, // Will come from paper_milestone table
      achieved: false,
      achievedAt: null,
    };
  } catch {
    return null;
  }
}

export function PaperMilestoneCard() {
  const mode = useBotMode((s) => s.mode);
  const { data } = usePolling(fetchMilestone, 30000);

  if (mode !== "paper" || !data) return null;

  const pct = Math.min(100, (data.profitableDays / data.targetDays) * 100);
  const remaining = Math.max(0, data.targetDays - data.profitableDays);

  return (
    <Card className="bg-card/60 border-border/40 border-amber-500/20">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm font-medium text-amber-400">
          <Trophy className="h-4 w-4" />
          Paper Trading Milestone
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <Progress value={pct} className="h-2" />
        <div className="flex items-center justify-between">
          <span className="text-xs text-muted-foreground">
            {data.profitableDays} / {data.targetDays} profitable days
          </span>
          <span className="text-xs text-amber-400">
            {remaining > 0 ? `${remaining} days remaining` : "Milestone reached!"}
          </span>
        </div>
        {data.achieved && (
          <p className="rounded bg-green-500/10 px-2 py-1 text-xs text-green-400">
            Target reached! System recommends reviewing live mode.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
