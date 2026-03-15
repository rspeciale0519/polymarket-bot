"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  BarChart3,
  LineChart,
  Store,
  Settings,
  Activity,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useBotMode } from "@/stores/bot-mode";

const navItems = [
  { href: "/overview", label: "Overview", icon: LayoutDashboard },
  { href: "/positions", label: "Positions", icon: BarChart3 },
  { href: "/markets", label: "Markets", icon: Store },
  { href: "/analytics", label: "Analytics", icon: LineChart },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();
  const { connected, isRunning } = useBotMode();

  return (
    <aside className="flex h-screen w-[220px] flex-col border-r border-border/50 bg-card/50">
      {/* Logo */}
      <div className="flex items-center gap-2.5 border-b border-border/50 px-5 py-5">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10">
          <Activity className="h-4 w-4 text-primary" />
        </div>
        <div>
          <h1
            className="text-sm font-semibold tracking-tight"
            style={{ fontFamily: "var(--font-display)" }}
          >
            PolyBot
          </h1>
          <p className="text-[10px] uppercase tracking-widest text-muted-foreground">
            Market Maker
          </p>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 space-y-1 px-3 py-4">
        {navItems.map((item) => {
          const isActive = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
                isActive
                  ? "bg-primary/10 text-primary font-medium"
                  : "text-muted-foreground hover:bg-accent hover:text-foreground"
              )}
            >
              <item.icon className="h-4 w-4" />
              {item.label}
            </Link>
          );
        })}
      </nav>

      {/* Connection status */}
      <div className="border-t border-border/50 px-4 py-3">
        <div className="flex items-center gap-2">
          <div className="relative">
            <div
              className={cn(
                "h-2 w-2 rounded-full",
                connected ? "bg-green-500" : "bg-red-500"
              )}
            />
            {connected && (
              <div
                className="absolute inset-0 h-2 w-2 rounded-full bg-green-500"
                style={{
                  animation: "pulse-ring 2s ease-out infinite",
                }}
              />
            )}
          </div>
          <span className="text-xs text-muted-foreground">
            {connected
              ? isRunning
                ? "Engine Running"
                : "Connected"
              : "Disconnected"}
          </span>
        </div>
      </div>
    </aside>
  );
}
