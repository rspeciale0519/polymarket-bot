"use client";

import { usePolling } from "./use-polling";
import type { PortfolioPoint } from "@/types/bot";

async function fetchHistory(hours: number): Promise<PortfolioPoint[]> {
  const res = await fetch(`/api/portfolio-history?hours=${hours}`);
  if (!res.ok) throw new Error("Failed to fetch portfolio history");
  const json = await res.json();
  return json.data;
}

export function usePortfolioHistory(hours: number = 24) {
  return usePolling(() => fetchHistory(hours), 30000);
}
