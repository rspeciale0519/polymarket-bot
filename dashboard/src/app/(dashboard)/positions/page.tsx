"use client";

import { useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { usePositions } from "@/hooks/use-positions";
import { useOrders, cancelOrder, cancelAllOrders } from "@/hooks/use-orders";
import { useTrades } from "@/hooks/use-trades";
import { formatCents, formatPnl, pnlColor, cn } from "@/lib/utils";
import { toast } from "sonner";
import { X, Trash2 } from "lucide-react";

export default function PositionsPage() {
  const { data: positions, loading: posLoading } = usePositions();
  const { data: orders, loading: ordLoading, refetch: refetchOrders } = useOrders();
  const [page] = useState(1);
  const { data: tradesData, loading: trLoading } = useTrades(page, 25);

  const handleCancelOrder = async (orderId: string) => {
    const ok = await cancelOrder(orderId);
    if (ok) {
      toast.success("Order cancelled");
      refetchOrders();
    } else {
      toast.error("Failed to cancel order");
    }
  };

  const handleCancelAll = async () => {
    const ok = await cancelAllOrders();
    if (ok) {
      toast.success("All orders cancelled");
      refetchOrders();
    } else {
      toast.error("Failed to cancel orders");
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold tracking-tight" style={{ fontFamily: "var(--font-display)" }}>
          Positions & Orders
        </h2>
        <p className="text-sm text-muted-foreground">Active positions, open orders, and trade history</p>
      </div>

      <Tabs defaultValue="positions">
        <TabsList>
          <TabsTrigger value="positions">
            Positions
            {positions && <Badge variant="secondary" className="ml-2 text-[10px]">{positions.length}</Badge>}
          </TabsTrigger>
          <TabsTrigger value="orders">
            Orders
            {orders && <Badge variant="secondary" className="ml-2 text-[10px]">{orders.length}</Badge>}
          </TabsTrigger>
          <TabsTrigger value="history">Trade History</TabsTrigger>
        </TabsList>

        <TabsContent value="positions">
          <Card className="bg-card/60 border-border/40">
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Market</TableHead>
                    <TableHead>Side</TableHead>
                    <TableHead className="text-right">Size</TableHead>
                    <TableHead className="text-right">Entry</TableHead>
                    <TableHead className="text-right">Current</TableHead>
                    <TableHead className="text-right">Unrealized P&L</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {posLoading ? (
                    <TableRow><TableCell colSpan={6}><Skeleton className="h-8 w-full" /></TableCell></TableRow>
                  ) : !positions?.length ? (
                    <TableRow><TableCell colSpan={6} className="text-center text-muted-foreground py-8">No open positions</TableCell></TableRow>
                  ) : positions.map((p) => (
                    <TableRow key={p.id}>
                      <TableCell className="font-mono text-xs">{p.ticker}</TableCell>
                      <TableCell>
                        <Badge variant={p.side === "YES" ? "default" : "secondary"} className="text-[10px]">
                          {p.side}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right font-mono">{p.size}</TableCell>
                      <TableCell className="text-right font-mono">{formatCents(p.entryPriceCents)}</TableCell>
                      <TableCell className="text-right font-mono">{formatCents(p.currentPriceCents)}</TableCell>
                      <TableCell className={cn("text-right font-mono", pnlColor(p.unrealizedPnlCents))}>
                        {formatPnl(p.unrealizedPnlCents)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="orders">
          <div className="mb-3 flex justify-end">
            <Button variant="destructive" size="sm" onClick={handleCancelAll} disabled={!orders?.length}>
              <Trash2 className="mr-1.5 h-3.5 w-3.5" /> Cancel All
            </Button>
          </div>
          <Card className="bg-card/60 border-border/40">
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Market</TableHead>
                    <TableHead>Side</TableHead>
                    <TableHead>Action</TableHead>
                    <TableHead className="text-right">Price</TableHead>
                    <TableHead className="text-right">Size</TableHead>
                    <TableHead className="text-right">Cancel</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {ordLoading ? (
                    <TableRow><TableCell colSpan={6}><Skeleton className="h-8 w-full" /></TableCell></TableRow>
                  ) : !orders?.length ? (
                    <TableRow><TableCell colSpan={6} className="text-center text-muted-foreground py-8">No open orders</TableCell></TableRow>
                  ) : orders.map((o) => (
                    <TableRow key={o.id}>
                      <TableCell className="font-mono text-xs">{o.ticker}</TableCell>
                      <TableCell><Badge variant="outline" className="text-[10px]">{o.side}</Badge></TableCell>
                      <TableCell className="text-xs uppercase">{o.action}</TableCell>
                      <TableCell className="text-right font-mono">{formatCents(o.priceCents)}</TableCell>
                      <TableCell className="text-right font-mono">{o.size}</TableCell>
                      <TableCell className="text-right">
                        <Button variant="ghost" size="sm" onClick={() => handleCancelOrder(o.externalOrderId)}>
                          <X className="h-3.5 w-3.5 text-muted-foreground hover:text-destructive" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="history">
          <Card className="bg-card/60 border-border/40">
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Time</TableHead>
                    <TableHead>Market</TableHead>
                    <TableHead>Side</TableHead>
                    <TableHead>Action</TableHead>
                    <TableHead className="text-right">Qty</TableHead>
                    <TableHead className="text-right">Price</TableHead>
                    <TableHead className="text-right">Fee</TableHead>
                    <TableHead className="text-right">P&L</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {trLoading ? (
                    <TableRow><TableCell colSpan={8}><Skeleton className="h-8 w-full" /></TableCell></TableRow>
                  ) : !tradesData?.trades?.length ? (
                    <TableRow><TableCell colSpan={8} className="text-center text-muted-foreground py-8">No trades yet</TableCell></TableRow>
                  ) : tradesData.trades.map((t) => (
                    <TableRow key={t.id}>
                      <TableCell className="font-mono text-[11px] text-muted-foreground">
                        {new Date(t.createdAt).toLocaleString()}
                      </TableCell>
                      <TableCell className="font-mono text-xs">{t.ticker}</TableCell>
                      <TableCell><Badge variant="outline" className="text-[10px]">{t.side}</Badge></TableCell>
                      <TableCell className="text-xs uppercase">{t.action}</TableCell>
                      <TableCell className="text-right font-mono">{t.count}</TableCell>
                      <TableCell className="text-right font-mono">{formatCents(t.priceCents)}</TableCell>
                      <TableCell className="text-right font-mono text-muted-foreground">{formatCents(t.feeCents)}</TableCell>
                      <TableCell className={cn("text-right font-mono", pnlColor(t.pnlCents))}>
                        {formatPnl(t.pnlCents)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
