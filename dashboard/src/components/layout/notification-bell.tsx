"use client";

import { Bell } from "lucide-react";
import { useNotifications, markAllRead } from "@/hooks/use-notifications";
import { cn } from "@/lib/utils";

export function NotificationBell() {
  const { data: notifications } = useNotifications();
  const unreadCount = notifications?.length ?? 0;

  const handleClick = async () => {
    if (unreadCount > 0) {
      await markAllRead();
    }
  };

  return (
    <button
      onClick={handleClick}
      className="relative rounded-lg p-2 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
    >
      <Bell className="h-4 w-4" />
      {unreadCount > 0 && (
        <span className="absolute -right-0.5 -top-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-primary text-[10px] font-bold text-primary-foreground">
          {unreadCount > 9 ? "9+" : unreadCount}
        </span>
      )}
    </button>
  );
}
