"use client";

import { useEffect, useRef } from "react";
import { usePolling } from "./use-polling";
import type { NotificationItem } from "@/types/bot";

async function fetchNotifications(): Promise<NotificationItem[]> {
  const res = await fetch("/api/notifications?unread=true");
  if (!res.ok) throw new Error("Failed to fetch notifications");
  const json = await res.json();
  return json.data;
}

export function useNotifications() {
  const result = usePolling(fetchNotifications, 5000);
  const seenIds = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (!result.data) return;

    for (const notif of result.data) {
      if (!seenIds.current.has(notif.id)) {
        seenIds.current.add(notif.id);
        // Toast will be triggered by the component consuming this hook
      }
    }
  }, [result.data]);

  return result;
}

export async function markAllRead(): Promise<boolean> {
  const res = await fetch("/api/notifications/read-all", { method: "POST" });
  return res.ok;
}
