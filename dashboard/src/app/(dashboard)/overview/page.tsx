"use client";

import { useOverview } from "@/hooks/use-overview";
import { MetricsRow } from "@/components/overview/metrics-row";
import { EquityCurveCard } from "@/components/overview/equity-curve-card";
import { SystemStatusCard } from "@/components/overview/system-status-card";
import { PaperMilestoneCard } from "@/components/overview/paper-milestone-card";

export default function OverviewPage() {
  const { data, loading } = useOverview();

  return (
    <div className="space-y-6">
      <div>
        <h2
          className="text-xl font-semibold tracking-tight"
          style={{ fontFamily: "var(--font-display)" }}
        >
          Overview
        </h2>
        <p className="text-sm text-muted-foreground">
          Real-time engine status and performance
        </p>
      </div>

      <MetricsRow data={data} loading={loading} />

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <EquityCurveCard />
        </div>
        <div className="space-y-4">
          <SystemStatusCard data={data} />
          <PaperMilestoneCard />
        </div>
      </div>
    </div>
  );
}
