"use client";

import { usePolling } from "./use-polling";
import type { BotSettings } from "@/types/bot";

async function fetchSettings(): Promise<BotSettings> {
  const res = await fetch("/api/settings");
  if (!res.ok) throw new Error("Failed to fetch settings");
  const json = await res.json();
  return json.data;
}

export function useSettings() {
  return usePolling(fetchSettings, 10000);
}

export async function updateSettings(
  updates: Partial<BotSettings>
): Promise<boolean> {
  const res = await fetch("/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });
  return res.ok;
}
