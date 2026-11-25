"use client";

import { useState } from "react";

import { Badge, Button, Card, CardHeader, Empty, ErrorNote, PageTitle, Stat, Table, statusTone } from "@/components/ui";
import { API_URL, api, useApi } from "@/lib/api";
import type { JobRow, Status } from "@/lib/types";
import { ago, fmtTime } from "@/lib/utils";

type Health = { ok: boolean; supervisor_heartbeat: string | null; supervisor_stale: boolean };

function useHealth() {
  const [h, setH] = useState<Health | null>(null);
  const [err, setErr] = useState<string | null>(null);
  return {
    h,
    err,
    check: async () => {
      try {
        const r = await fetch(`${API_URL}/healthz`, { cache: "no-store" });
        setH(await r.json());
        setErr(null);
      } catch (e) {
        setErr(e instanceof Error ? e.message : String(e));
      }
    },
  };
}

export default function System() {
  const st = useApi<Status>("/api/status", 10000);
  const failed = useApi<JobRow[]>("/api/jobs?status=failed&limit=100", 15000);
  const recent = useApi<JobRow[]>("/api/jobs?limit=100", 10000);
  const health = useHealth();
  const [err, setErr] = useState<string | null>(null);
  const c = st.data?.counts;

  return (
    <>
      <PageTitle title="System health" desc="Workers, queue and errors. Failed jobs retry automatically with backoff; dead-lettered ones are listed here." />
      <ErrorNote error={err || st.error || health.err} />
      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label="Supervisor" value={st.data ? (st.data.autopilot.supervisor_stale ? "stale" : "healthy") : "–"} hint={`heartbeat ${ago(st.data?.autopilot.last_tick_at)}`} />
        <Stat label="Pending" value={c?.jobs_pending ?? "–"} />
        <Stat label="Running" value={c?.jobs_running ?? "–"} />
        <Stat label="Blocked" value={c?.jobs_blocked ?? "–"} />
        <Stat label="Dead-lettered" value={c?.jobs_failed ?? "–"} />
      </div>
      <div className="mb-6 flex items-center gap-3">
        <Button size="sm" onClick={health.check}>Check API health</Button>
        {health.h && <span className="text-sm text-muted">API {health.h.ok ? "ok" : "down"} · supervisor {health.h.supervisor_stale ? "stale" : "reporting"}</span>}
      </div>
      <div className="space-y-6">
        <Card>
          <CardHeader title="Dead-letter queue" desc="Jobs that exhausted their retries. Retrying is optional; the rest of the pipeline keeps running." />
          {failed.data && failed.data.length === 0 ? (
            <Empty>Empty.</Empty>
          ) : (
            <Table head={["Job", "Kind", "Attempts", "Error", ""]}>
              {failed.data?.map((j) => (
                <tr key={j.id}>
                  <td className="text-muted">#{j.id}</td>
                  <td>{j.kind}</td>
                  <td className="tabular-nums">{j.attempts}/{j.max_attempts}</td>
                  <td className="max-w-md truncate text-xs text-muted" title={j.last_error}>{j.last_error.split("\n")[0]}</td>
                  <td className="text-right">
                    <Button
                      size="sm"
                      onClick={async () => {
                        try {
                          await api(`/api/jobs/${j.id}/retry`, { method: "POST" });
                          await failed.reload();
                        } catch (e) {
                          setErr(e instanceof Error ? e.message : String(e));
                        }
                      }}
                    >
                      Retry
                    </Button>
                  </td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
        <Card>
          <CardHeader title="Recent jobs" />
          {recent.data && recent.data.length === 0 ? (
            <Empty>No jobs yet.</Empty>
          ) : (
            <Table head={["Job", "Kind", "Status", "Attempts", "Next run", "Last note"]}>
              {recent.data?.map((j) => (
                <tr key={j.id}>
                  <td className="text-muted">#{j.id}</td>
                  <td>{j.kind}</td>
                  <td><Badge tone={statusTone(j.status)}>{j.status}</Badge></td>
                  <td className="tabular-nums">{j.attempts}</td>
                  <td className="whitespace-nowrap text-muted">{j.status === "pending" ? fmtTime(j.run_after) : "–"}</td>
                  <td className="max-w-sm truncate text-xs text-muted" title={j.last_error}>{j.last_error.split("\n")[0]}</td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
      </div>
    </>
  );
}
