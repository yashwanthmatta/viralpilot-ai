"use client";

import {
  Activity,
  Bot,
  CalendarClock,
  Clapperboard,
  Compass,
  DollarSign,
  Gauge,
  LogOut,
  Rss,
  Server,
  Settings,
  Share2,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { api, useApi } from "@/lib/api";
import type { Status } from "@/lib/types";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Command center", icon: Gauge },
  { href: "/activity", label: "Live activity", icon: Activity },
  { href: "/agents", label: "AI agents", icon: Bot },
  { href: "/discovery", label: "Content discovery", icon: Compass },
  { href: "/library", label: "Video library", icon: Clapperboard },
  { href: "/publishing", label: "Publishing", icon: CalendarClock },
  { href: "/accounts", label: "Social accounts", icon: Share2 },
  { href: "/sources", label: "Sources", icon: Rss },
  { href: "/costs", label: "Costs & revenue", icon: DollarSign },
  { href: "/system", label: "System health", icon: Server },
  { href: "/security", label: "Security", icon: ShieldCheck },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const { data } = useApi<Status>("/api/status", 15000);
  const on = data?.autopilot.enabled;
  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-line bg-panel/60 px-3 py-4 md:flex">
        <div className="mb-6 flex items-center gap-2 px-2">
          <div className="grid h-7 w-7 place-items-center rounded-md bg-accent/15 text-accent">
            <Gauge size={16} />
          </div>
          <span className="text-sm font-semibold">ViralPilot</span>
        </div>
        <nav className="flex-1 space-y-0.5">
          {NAV.map(({ href, label, icon: Icon }) => (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm text-muted hover:bg-panel-2 hover:text-fg",
                path === href && "bg-panel-2 text-fg",
              )}
            >
              <Icon size={15} />
              {label}
            </Link>
          ))}
        </nav>
        <div className="space-y-2 border-t border-line px-2 pt-3">
          <div className="flex items-center gap-2 text-xs text-muted">
            <span className={cn("h-2 w-2 rounded-full", on ? "bg-go" : "bg-muted/50")} />
            Autopilot {data ? (on ? "running" : "stopped") : "…"}
          </div>
          <button
            className="flex items-center gap-2 text-xs text-muted hover:text-fg"
            onClick={async () => {
              await api("/api/auth/logout", { method: "POST" });
              router.push("/login");
            }}
          >
            <LogOut size={13} /> Sign out
          </button>
        </div>
      </aside>
      <div className="min-w-0 flex-1">
        <div className="flex gap-1 overflow-x-auto border-b border-line px-4 py-2 md:hidden">
          {NAV.map(({ href, label }) => (
            <Link key={href} href={href} className={cn("whitespace-nowrap rounded px-2 py-1 text-xs text-muted", path === href && "bg-panel-2 text-fg")}>
              {label}
            </Link>
          ))}
        </div>
        <main className="mx-auto max-w-6xl px-5 py-8 md:px-8">{children}</main>
      </div>
    </div>
  );
}
