"use client";

import { useBotMode } from "@/stores/bot-mode";
import { cn } from "@/lib/utils";

export function ModeBadge() {
  const mode = useBotMode((s) => s.mode);
  const isPaper = mode === "paper";

  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold tracking-wide uppercase",
        isPaper
          ? "bg-amber-500/10 text-amber-400 border border-amber-500/20"
          : "bg-green-500/10 text-green-400 border border-green-500/20"
      )}
      style={{ fontFamily: "var(--font-mono)" }}
    >
      <span
        className={cn(
          "mr-1.5 h-1.5 w-1.5 rounded-full",
          isPaper ? "bg-amber-400" : "bg-green-400"
        )}
      />
      {isPaper ? "Paper" : "Live"}
    </span>
  );
}
