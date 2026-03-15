"use client";

import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useMarkets, toggleMarket } from "@/hooks/use-markets";
import { toast } from "sonner";
import { Store } from "lucide-react";

export default function MarketsPage() {
  const { data: markets, loading, refetch } = useMarkets();

  const handleToggle = async (ticker: string, enabled: boolean) => {
    const ok = await toggleMarket(ticker, enabled);
    if (ok) {
      toast.success(`${ticker} ${enabled ? "enabled" : "disabled"}`);
      refetch();
    } else {
      toast.error("Failed to update market");
    }
  };

  const activeCount = markets?.filter((m) => m.enabled && !m.excluded).length ?? 0;
  const pausedCount = markets?.filter((m) => !m.enabled && !m.excluded).length ?? 0;
  const excludedCount = markets?.filter((m) => m.excluded).length ?? 0;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold tracking-tight" style={{ fontFamily: "var(--font-display)" }}>
          Markets
        </h2>
        <p className="text-sm text-muted-foreground">Markets the engine is monitoring and quoting</p>
      </div>

      <div className="flex items-center gap-3">
        <Badge variant="default" className="text-xs">Active: {activeCount}</Badge>
        <Badge variant="secondary" className="text-xs">Paused: {pausedCount}</Badge>
        <Badge variant="destructive" className="text-xs">Excluded: {excludedCount}</Badge>
      </div>

      <Card className="bg-card/60 border-border/40">
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Market</TableHead>
                <TableHead>Ticker</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Enabled</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow><TableCell colSpan={4}><Skeleton className="h-8 w-full" /></TableCell></TableRow>
              ) : !markets?.length ? (
                <TableRow>
                  <TableCell colSpan={4} className="py-12 text-center">
                    <Store className="mx-auto h-8 w-8 text-muted-foreground/30" />
                    <p className="mt-2 text-sm text-muted-foreground">No markets configured</p>
                    <p className="text-xs text-muted-foreground">Markets will appear after the engine scans</p>
                  </TableCell>
                </TableRow>
              ) : markets.map((m) => (
                <TableRow key={m.id}>
                  <TableCell className="text-sm">{m.title || m.ticker}</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">{m.ticker}</TableCell>
                  <TableCell>
                    {m.excluded ? (
                      <Badge variant="destructive" className="text-[10px]">Excluded</Badge>
                    ) : m.enabled ? (
                      <Badge variant="default" className="text-[10px]">Active</Badge>
                    ) : (
                      <Badge variant="secondary" className="text-[10px]">Paused</Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-right">
                    <Switch
                      checked={m.enabled}
                      onCheckedChange={(v) => handleToggle(m.ticker, v)}
                      disabled={m.excluded}
                    />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
