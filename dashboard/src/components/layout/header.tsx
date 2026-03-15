"use client";

import { ModeBadge } from "./mode-badge";
import { ModeToggle } from "./mode-toggle";
import { NotificationBell } from "./notification-bell";

export function Header() {
  return (
    <header className="flex h-14 items-center justify-between border-b border-border/50 bg-card/30 px-6">
      <div className="flex items-center gap-4">
        <ModeBadge />
      </div>
      <div className="flex items-center gap-4">
        <ModeToggle />
        <div className="h-5 w-px bg-border" />
        <NotificationBell />
      </div>
    </header>
  );
}
