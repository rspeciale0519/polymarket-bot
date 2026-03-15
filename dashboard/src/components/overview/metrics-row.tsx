"use client";

import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatCents, formatPnl, pnlColor, cn } from "@/lib/utils";
import type { OverviewData } from "@/types/bot";
import {
  Wallet,
  TrendingUp,
  TrendingDown,
  BarChart3,
  ShoppingCart,
  CalendarDays,
  Timer,
} from "lucide-react";

interface Props {
  data: OverviewData | null;
  loading: boolean;
}

const metrics = [
  { key: "balanceCents", label: "Balance", icon: Wallet, format: formatCents, color: "" },
  { key: "todayPnlCents", label: "Today P&L", icon: Timer, format: formatPnl, color: "pnl" },
  { key: "weekPnlCents", label: "Week P&L", icon: CalendarDays, format: formatPnl, color: "pnl" },
  { key: "monthPnlCents", label: "Month P&L", icon: TrendingUp, format: formatPnl, color: "pnl" },
  { key: "allTimePnlCents", label: "All-Time P&L", icon: BarChart3, format: formatPnl, color: "pnl" },
  { key: "activePositions", label: "Positions", icon: TrendingDown, format: (v: number) => String(v), color: "" },
  { key: "openOrders", label: "Open Orders", icon: ShoppingCart, format: (v: number) => String(v), color: "" },
] as const;

export function MetricsRow({ data, loading }: Props) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-7">
      {metrics.map((m) => (
        <Card key={m.key} className="bg-card/60 border-border/40">
          <CardContent className="p-4">
            <div className="flex items-center gap-2 text-muted-foreground">
              <m.icon className="h-3.5 w-3.5" />
              <span className="text-[11px] uppercase tracking-wider">{m.label}</span>
            </div>
            {loading ? (
              <Skeleton className="mt-2 h-6 w-20" />
            ) : (
              <p
                className={cn(
                  "mt-1.5 text-lg font-semibold tabular-nums",
                  m.color === "pnl" && data
                    ? pnlColor((data as unknown as Record<string, number>)[m.key] ?? 0)
                    : "text-foreground"
                )}
                style={{ fontFamily: "var(--font-mono)" }}
              >
                {data ? m.format((data as unknown as Record<string, number>)[m.key] ?? 0) : "—"}
              </p>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
