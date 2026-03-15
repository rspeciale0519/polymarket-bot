import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatCents(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`;
}

export function formatPnl(cents: number): string {
  const prefix = cents >= 0 ? "+" : "";
  return `${prefix}$${(cents / 100).toFixed(2)}`;
}

export function formatPercent(value: number): string {
  const prefix = value >= 0 ? "+" : "";
  return `${prefix}${value.toFixed(2)}%`;
}

export function pnlColor(cents: number): string {
  if (cents > 0) return "pnl-positive";
  if (cents < 0) return "pnl-negative";
  return "text-muted-foreground";
}
