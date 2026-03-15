"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { OverviewData } from "@/types/bot";
import { AlertTriangle, CheckCircle, XCircle, Wifi, WifiOff } from "lucide-react";

interface Props {
  data: OverviewData | null;
}

export function SystemStatusCard({ data }: Props) {
  if (!data) return null;

  const cbState = data.circuitBreakerState;

  return (
    <Card className="bg-card/60 border-border/40">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          System Status
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-xs text-muted-foreground">Connection</span>
          <div className="flex items-center gap-1.5">
            {data.connected ? (
              <Wifi className="h-3.5 w-3.5 text-green-400" />
            ) : (
              <WifiOff className="h-3.5 w-3.5 text-red-400" />
            )}
            <span className={cn("text-xs", data.connected ? "text-green-400" : "text-red-400")}>
              {data.connected ? "Connected" : "Disconnected"}
            </span>
          </div>
        </div>

        <div className="flex items-center justify-between">
          <span className="text-xs text-muted-foreground">Engine</span>
          <span className={cn("text-xs", data.isRunning ? "text-green-400" : "text-muted-foreground")}>
            {data.isPaused ? "Paused" : data.isRunning ? "Running" : "Stopped"}
          </span>
        </div>

        <div className="flex items-center justify-between">
          <span className="text-xs text-muted-foreground">Circuit Breakers</span>
          <div className="flex items-center gap-1.5">
            {cbState === "ok" && <CheckCircle className="h-3.5 w-3.5 text-green-400" />}
            {cbState === "warning" && <AlertTriangle className="h-3.5 w-3.5 text-amber-400" />}
            {cbState === "halted" && <XCircle className="h-3.5 w-3.5 text-red-400" />}
            <span className={cn(
              "text-xs",
              cbState === "ok" ? "text-green-400" : cbState === "warning" ? "text-amber-400" : "text-red-400"
            )}>
              {cbState === "ok" ? "OK" : cbState === "warning" ? "Warning" : "Halted"}
            </span>
          </div>
        </div>

        {data.circuitBreakerReason && (
          <p className="rounded bg-red-500/10 px-2 py-1 text-xs text-red-400">
            {data.circuitBreakerReason}
          </p>
        )}

        {data.lastTradeAt && (
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground">Last Trade</span>
            <span className="text-xs text-foreground" style={{ fontFamily: "var(--font-mono)" }}>
              {new Date(data.lastTradeAt).toLocaleTimeString()}
            </span>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
