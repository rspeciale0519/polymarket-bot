"use client";

import { useCallback, useState } from "react";
import { usePolling } from "./use-polling";
import type { TradeRow } from "@/types/bot";

interface TradesResult {
  trades: TradeRow[];
  total: number;
}

async function fetchTrades(
  page: number,
  pageSize: number
): Promise<TradesResult> {
  const res = await fetch(
    `/api/trades?page=${page}&pageSize=${pageSize}`
  );
  if (!res.ok) throw new Error("Failed to fetch trades");
  const json = await res.json();
  return json.data;
}

export function useTrades(page: number = 1, pageSize: number = 25) {
  return usePolling(() => fetchTrades(page, pageSize), 10000);
}
