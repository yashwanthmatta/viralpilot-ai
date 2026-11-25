"use client";

import { AlertTriangle, Power, Square } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Badge, Button, Card, CardBody, CardHeader, Empty, ErrorNote, Stat } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import type { Decision, Status } from "@/lib/types";
import { ago, fmtTime, usd } from "@/lib/utils";

function Meter({ value, max }: { value: number; max: number }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 100;
  return (
    <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-bg">
      <div className={pct >= 90 ? "h-full bg-stop" : pct >= 70 ? "h-full bg-warn" : "h-full bg-go"} style={{ width: `${pct}%` }} />
    </div>
  );
}

export default function CommandCenter() {
  const { data: st, error, reload } = useApi<Status>("/api/status", 10000);
  const { data: decisions } = useApi<Decision[]>("/api/decisions?limit=8", 10000);
  const r = st?.revenue;
  const [busy, setBusy] = useState(false);
  const [actionErr, setActionErr] = useState<string | null>(null);

  async function toggle(to: "start" | "stop") {
    setBusy(true);
    setActionErr(null);
    try {
      await api(`/api/autopilot/${to}`, { method: "POST" });
      await reload();
    } catch (e) {
      setActionErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const on = st?.autopilot.enabled ?? false;
  const c = st?.counts;

  return (
    <div className="space-y-6">
      <Card className="overflow-hidden">
        <div className="flex flex-col gap-6 p-6 md:flex-row md:items-center md:justify-between">
          <div>
            <div className="flex items-center gap-3">
              <span className={`relative flex h-3 w-3`}>
                {on && <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-go opacity-60" />}
                <span className={`relative inline-flex h-3 w-3 rounded-full ${on ? "bg-go" : "bg-muted/50"}`} />
              </span>
              <h1 className="text-2xl font-semibold tracking-tight">Autopilot {st ? (on ? "running" : "stopped") : "…"}</h1>
            </div>
            <p className="mt-2 text-sm text-muted">
              {st?.autopilot.reason} · changed {ago(st?.autopilot.changed_at)} · supervisor heartbeat {ago(st?.autopilot.last_tick_at)}
              {st?.autopilot.supervisor_stale && <Badge tone="warn" className="ml-2">worker not reporting</Badge>}
            </p>
          </div>
          <div className="flex gap-3">
            <Button variant="go" size="xl" disabled={busy || on || !st} onClick={() => toggle("start")}>
              <Power size={18} /> START AUTOPILOT
            </Button>
            <Button variant="stop" size="xl" disabled={busy || !on} onClick={() => toggle("stop")}>
              <Square size={16} /> STOP AUTOPILOT
            </Button>
          </div>
        </div>
        {(actionErr || error) && (
          <div className="border-t border-line px-6 py-3">
            <ErrorNote error={actionErr || error} />
          </div>
        )}
      </Card>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
        <Stat label="Confirmed today" value={r ? usd(r.confirmed_today) : "–"} hint="verified payouts only" />
        <Stat label="Confirmed this month" value={r ? usd(r.confirmed_month) : "–"} hint={r?.next_milestone ? `next milestone ${usd(r.next_milestone)}` : undefined} />
        <Stat label="Pending" value={r ? usd(r.pending) : "–"} hint="approved, not yet paid" />
        <Stat label="Net this month" value={r ? usd(r.net_month_confirmed) : "–"} hint="confirmed minus spend" />
        <Stat label="Progress to $100k/mo" value={r ? `${(r.progress_to_100k * 100).toFixed(3)}%` : "–"} />
        <Stat label="Active campaigns" value={r?.active_campaigns ?? "–"} />
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-5">
        <Stat label="Discovered" value={c?.discovered ?? "–"} hint={c ? `${c.rights_rejected} rejected on rights` : undefined} />
        <Stat label="Analyzed" value={c?.analyzed ?? "–"} hint={c ? `${c.imported} imported` : undefined} />
        <Stat label="Clips" value={c?.clips ?? "–"} hint={c ? `${c.editing} being edited` : undefined} />
        <Stat label="Scheduled" value={c?.scheduled ?? "–"} />
        <Stat label="Published" value={c?.published ?? "–"} hint="platform-confirmed only" />
        <Stat label="Total views" value={c ? c.total_views.toLocaleString() : "–"} hint="from platform metrics" />
        <Stat label="Errors auto-resolved" value={c?.errors_auto_recovered ?? "–"} />
        <Stat label="Jobs queued" value={c ? c.jobs_pending + c.jobs_running : "–"} hint={c ? `${c.jobs_blocked} waiting on blockers` : undefined} />
        <Stat label="Dead-lettered" value={c?.jobs_failed ?? "–"} />
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card>
          <CardHeader title="Spend" desc="Hard limits. Paid steps stop when reached." right={<Link href="/settings" className="text-xs text-muted hover:text-fg">Edit</Link>} />
          <CardBody className="space-y-4">
            {st && (
              <>
                <div>
                  <div className="flex justify-between text-sm"><span>Today</span><span className="tabular-nums">{usd(st.spend.today)} / {usd(st.spend.daily_limit)}</span></div>
                  <Meter value={st.spend.today} max={st.spend.daily_limit} />
                </div>
                <div>
                  <div className="flex justify-between text-sm"><span>This month</span><span className="tabular-nums">{usd(st.spend.month)} / {usd(st.spend.monthly_limit)}</span></div>
                  <Meter value={st.spend.month} max={st.spend.monthly_limit} />
                </div>
                <div>
                  <div className="flex justify-between text-sm"><span>Lifetime cap</span><span className="tabular-nums">{usd(st.spend.total)} / {usd(st.spend.total_limit)}</span></div>
                  <Meter value={st.spend.total} max={st.spend.total_limit} />
                </div>
                <p className="text-xs text-muted">Max {st.spend.max_videos_per_day} unique videos/day · {usd(st.spend.per_video_limit)} per video</p>
              </>
            )}
          </CardBody>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader title={`External blockers (${st?.blockers.length ?? 0})`} desc="Things only a platform approval, credential or later build phase can clear." />
          {st && st.blockers.length === 0 ? (
            <Empty>No blockers.</Empty>
          ) : (
            <div className="divide-y divide-line">
              {st?.blockers.map((b) => (
                <div key={b.key} className="flex gap-3 px-5 py-3">
                  <AlertTriangle size={16} className="mt-0.5 shrink-0 text-warn" />
                  <div>
                    <div className="text-sm">{b.title}</div>
                    <div className="text-xs text-muted">{b.detail}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title="Upcoming publishing" right={<Link href="/publishing" className="text-xs text-muted hover:text-fg">All</Link>} />
          {st && st.upcoming.length === 0 ? (
            <Empty>Nothing scheduled yet.</Empty>
          ) : (
            <div className="divide-y divide-line">
              {st?.upcoming.map((u) => (
                <div key={u.id} className="flex justify-between px-5 py-2.5 text-sm">
                  <span>Clip #{u.clip_id} → {u.platform}</span>
                  <span className="text-muted">{fmtTime(u.at)}</span>
                </div>
              ))}
            </div>
          )}
        </Card>
        <Card>
          <CardHeader title="Latest AI decisions" right={<Link href="/activity" className="text-xs text-muted hover:text-fg">All</Link>} />
          {decisions && decisions.length === 0 ? (
            <Empty>No decisions yet.</Empty>
          ) : (
            <div className="divide-y divide-line">
              {decisions?.map((d) => (
                <div key={d.id} className="px-5 py-2.5">
                  <div className="flex justify-between text-xs text-muted"><span>{d.agent}</span><span>{ago(d.at)}</span></div>
                  <div className="text-sm"><span className="text-accent">{d.action}</span> <span className="text-muted">{d.detail}</span></div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
