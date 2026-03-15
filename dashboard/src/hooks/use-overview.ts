"use client";

import { useEffect } from "react";
import { usePolling } from "./use-polling";
import { useBotMode } from "@/stores/bot-mode";
import type { OverviewData } from "@/types/bot";

async function fetchOverview(): Promise<OverviewData> {
  const res = await fetch("/api/overview");
  if (!res.ok) throw new Error("Failed to fetch overview");
  const json = await res.json();
  return json.data;
}

export function useOverview() {
  const result = usePolling(fetchOverview, 7000);
  const updateFromOverview = useBotMode((s) => s.updateFromOverview);

  useEffect(() => {
    if (result.data) {
      updateFromOverview({
        mode: result.data.mode,
        connected: result.data.connected,
        isRunning: result.data.isRunning,
        isPaused: result.data.isPaused,
      });
    }
  }, [result.data, updateFromOverview]);

  return result;
}
