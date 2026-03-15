"use client";

import { usePolling } from "./use-polling";
import type { PositionRow } from "@/types/bot";

async function fetchPositions(): Promise<PositionRow[]> {
  const res = await fetch("/api/positions");
  if (!res.ok) throw new Error("Failed to fetch positions");
  const json = await res.json();
  return json.data;
}

export function usePositions() {
  return usePolling(fetchPositions, 7000);
}
