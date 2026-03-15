"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useAnalytics } from "@/hooks/use-analytics";
import { usePortfolioHistory } from "@/hooks/use-portfolio-history";
import { formatCents, formatPnl, formatPercent, pnlColor, cn } from "@/lib/utils";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
} from "recharts";
import { Target, TrendingUp, Percent, DollarSign } from "lucide-react";

export default function AnalyticsPage() {
  const { data, loading } = useAnalytics();
  const { data: history } = usePortfolioHistory(168); // 7 days

  const cumulativePnlData = (history ?? []).map((p) => ({
    time: new Date(p.snapshotAt).toLocaleDateString([], { month: "short", day: "numeric" }),
    pnl: (p.equityCents - (history?.[0]?.equityCents ?? p.equityCents)) / 100,
  }));

  const capitalBreakdown = data
    ? [
        { name: "Deposits", value: Math.max(0, data.depositsCents / 100), color: "hsl(217, 91%, 60%)" },
        { name: "Trading P&L", value: Math.max(0, data.tradingPnlCents / 100), color: "hsl(142, 71%, 45%)" },
      ]
    : [];

  const stats = [
    { label: "Win Rate", value: data ? `${data.winRate.toFixed(1)}%` : "—", icon: Target },
    { label: "Profit Factor", value: data ? data.profitFactor.toFixed(2) : "—", icon: TrendingUp },
    { label: "Maker Ratio", value: data ? `${data.makerRatio.toFixed(0)}%` : "—", icon: Percent },
    { label: "Total Fees", value: data ? formatCents(data.totalFeesCents) : "—", icon: DollarSign },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold tracking-tight" style={{ fontFamily: "var(--font-display)" }}>
          Analytics
        </h2>
        <p className="text-sm text-muted-foreground">Performance metrics and P&L analysis</p>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {stats.map((s) => (
          <Card key={s.label} className="bg-card/60 border-border/40">
            <CardContent className="p-4">
              <div className="flex items-center gap-2 text-muted-foreground">
                <s.icon className="h-3.5 w-3.5" />
                <span className="text-[11px] uppercase tracking-wider">{s.label}</span>
              </div>
              {loading ? (
                <Skeleton className="mt-2 h-6 w-16" />
              ) : (
                <p className="mt-1.5 text-lg font-semibold" style={{ fontFamily: "var(--font-mono)" }}>
                  {s.value}
                </p>
              )}
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2 bg-card/60 border-border/40">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Cumulative P&L (7d)</CardTitle>
          </CardHeader>
          <CardContent>
            {cumulativePnlData.length < 2 ? (
              <div className="flex h-[220px] items-center justify-center text-sm text-muted-foreground">
                Waiting for data...
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <AreaChart data={cumulativePnlData}>
                  <defs>
                    <linearGradient id="pnlGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="hsl(142, 71%, 45%)" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="hsl(142, 71%, 45%)" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <XAxis dataKey="time" tick={{ fontSize: 10, fill: "hsl(215, 20%, 55%)" }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 10, fill: "hsl(215, 20%, 55%)" }} axisLine={false} tickLine={false} tickFormatter={(v) => `$${v}`} width={50} />
                  <Tooltip
                    contentStyle={{ background: "hsl(222, 47%, 8%)", border: "1px solid hsl(217, 33%, 17%)", borderRadius: "6px", fontSize: 12, fontFamily: "var(--font-mono)" }}
                    formatter={(value) => [`$${Number(value).toFixed(2)}`, "P&L"]}
                  />
                  <Area type="monotone" dataKey="pnl" stroke="hsl(142, 71%, 45%)" strokeWidth={2} fill="url(#pnlGrad)" />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        <Card className="bg-card/60 border-border/40">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Capital Breakdown</CardTitle>
          </CardHeader>
          <CardContent>
            {!data ? (
              <Skeleton className="h-[220px] w-full" />
            ) : (
              <div className="flex flex-col items-center">
                <ResponsiveContainer width="100%" height={160}>
                  <PieChart>
                    <Pie data={capitalBreakdown} dataKey="value" nameKey="name" cx="50%" cy="50%" innerRadius={40} outerRadius={65} paddingAngle={4}>
                      {capitalBreakdown.map((entry, i) => (
                        <Cell key={i} fill={entry.color} />
                      ))}
                    </Pie>
                    <Tooltip
                      contentStyle={{ background: "hsl(222, 47%, 8%)", border: "1px solid hsl(217, 33%, 17%)", borderRadius: "6px", fontSize: 12 }}
                      formatter={(value) => `$${Number(value).toFixed(2)}`}
                    />
                  </PieChart>
                </ResponsiveContainer>
                <div className="flex gap-4 text-xs">
                  <span className="flex items-center gap-1.5">
                    <span className="h-2 w-2 rounded-full bg-primary" /> Deposits
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="h-2 w-2 rounded-full" style={{ background: "hsl(142, 71%, 45%)" }} /> Trading P&L
                  </span>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
