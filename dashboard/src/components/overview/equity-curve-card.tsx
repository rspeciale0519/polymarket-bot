"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { usePortfolioHistory } from "@/hooks/use-portfolio-history";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

export function EquityCurveCard() {
  const { data, loading } = usePortfolioHistory(24);

  const chartData = (data ?? []).map((p) => ({
    time: new Date(p.snapshotAt).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    }),
    equity: p.equityCents / 100,
  }));

  return (
    <Card className="bg-card/60 border-border/40">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          Equity Curve (24h)
        </CardTitle>
      </CardHeader>
      <CardContent>
        {loading ? (
          <Skeleton className="h-[200px] w-full" />
        ) : chartData.length < 2 ? (
          <div className="flex h-[200px] items-center justify-center text-sm text-muted-foreground">
            Waiting for data...
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={200}>
            <AreaChart data={chartData}>
              <defs>
                <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="hsl(217, 91%, 60%)" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="hsl(217, 91%, 60%)" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis
                dataKey="time"
                tick={{ fontSize: 10, fill: "hsl(215, 20%, 55%)" }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                tick={{ fontSize: 10, fill: "hsl(215, 20%, 55%)" }}
                axisLine={false}
                tickLine={false}
                tickFormatter={(v) => `$${v}`}
                width={50}
              />
              <Tooltip
                contentStyle={{
                  background: "hsl(222, 47%, 8%)",
                  border: "1px solid hsl(217, 33%, 17%)",
                  borderRadius: "6px",
                  fontSize: 12,
                  fontFamily: "var(--font-mono)",
                }}
                labelStyle={{ color: "hsl(215, 20%, 55%)" }}
                formatter={(value) => [`$${Number(value).toFixed(2)}`, "Equity"]}
              />
              <Area
                type="monotone"
                dataKey="equity"
                stroke="hsl(217, 91%, 60%)"
                strokeWidth={2}
                fill="url(#equityGrad)"
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}
