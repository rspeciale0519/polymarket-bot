"use client";

import { usePolling } from "./use-polling";
import type { OrderRow } from "@/types/bot";

async function fetchOrders(): Promise<OrderRow[]> {
  const res = await fetch("/api/orders");
  if (!res.ok) throw new Error("Failed to fetch orders");
  const json = await res.json();
  return json.data;
}

export function useOrders() {
  return usePolling(fetchOrders, 5000);
}

export async function cancelOrder(orderId: string): Promise<boolean> {
  const res = await fetch(`/api/orders?id=${orderId}`, { method: "DELETE" });
  return res.ok;
}

export async function cancelAllOrders(): Promise<boolean> {
  const res = await fetch("/api/orders/cancel-all", { method: "POST" });
  return res.ok;
}
