"use client";

import { usePolling } from "./use-polling";
import type { AnalyticsData } from "@/types/bot";

async function fetchAnalytics(): Promise<AnalyticsData> {
  const res = await fetch("/api/analytics");
  if (!res.ok) throw new Error("Failed to fetch analytics");
  const json = await res.json();
  return json.data;
}

export function useAnalytics() {
  return usePolling(fetchAnalytics, 30000);
}
