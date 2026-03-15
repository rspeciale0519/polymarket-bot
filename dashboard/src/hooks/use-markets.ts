"use client";

import { usePolling } from "./use-polling";
import type { MarketRow } from "@/types/bot";

async function fetchMarkets(): Promise<MarketRow[]> {
  const res = await fetch("/api/markets");
  if (!res.ok) throw new Error("Failed to fetch markets");
  const json = await res.json();
  return json.data;
}

export function useMarkets() {
  return usePolling(fetchMarkets, 15000);
}

export async function toggleMarket(
  ticker: string,
  enabled: boolean
): Promise<boolean> {
  const res = await fetch(`/api/markets?ticker=${ticker}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
  return res.ok;
}
