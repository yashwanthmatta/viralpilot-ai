"use client";

import { useState } from "react";

import { Badge, Button, Card, CardBody, CardHeader, Empty, ErrorNote, Field, Input, PageTitle, Select, Stat, Table } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import type { Finance, RevenueRow, Split } from "@/lib/types";
import { fmtTime, usd } from "@/lib/utils";

function SplitTable({ title, data }: { title: string; data: Split }) {
  const rows = Object.entries(data);
  return (
    <Card>
      <CardHeader title={title} />
      {rows.length === 0 ? (
        <Empty>No revenue yet.</Empty>
      ) : (
        <Table head={["", "Confirmed", "Pending"]}>
          {rows.map(([k, v]) => (
            <tr key={k}>
              <td>{k}</td>
              <td className="tabular-nums">{usd(v.confirmed)}</td>
              <td className="tabular-nums text-muted">{usd(v.pending)}</td>
            </tr>
          ))}
        </Table>
      )}
    </Card>
  );
}

const EMPTY = { stream: "campaign", amount: "", status: "pending", evidence: "", external_ref: "" };

export default function Revenue() {
  const fin = useApi<Finance>("/api/finance", 30000);
  const rev = useApi<RevenueRow[]>("/api/revenue", 30000);
  const [form, setForm] = useState(EMPTY);
  const [err, setErr] = useState<string | null>(null);
  const o = fin.data?.overview;
  const m = fin.data?.milestones;

  async function run(fn: () => Promise<unknown>) {
    setErr(null);
    try {
      await fn();
      await Promise.all([fin.reload(), rev.reload()]);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <>
      <PageTitle title="Revenue" desc="Confirmed means paid or credited, with evidence. Pending means reported but not yet paid. Estimates are never counted as revenue." />
      <ErrorNote error={err || fin.error || rev.error} />
      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Confirmed today" value={o ? usd(o.confirmed_today) : "–"} />
        <Stat label="Confirmed this month" value={o ? usd(o.confirmed_month) : "–"} />
        <Stat label="Pending payments" value={o ? usd(o.pending) : "–"} hint="not yet received" />
        <Stat label="Net this month" value={o ? usd(o.net_month_confirmed) : "–"} hint="confirmed minus spend" />
      </div>

      <Card className="mb-6">
        <CardHeader title="Progress toward $100,000/month" desc={o?.next_milestone ? `Next milestone: ${usd(o.next_milestone)}/month` : undefined} />
        <CardBody>
          <div className="h-2 overflow-hidden rounded-full bg-bg">
            <div className="h-full bg-go" style={{ width: `${Math.max((o?.progress_to_100k ?? 0) * 100, 0.5)}%` }} />
          </div>
          <p className="mt-2 text-xs text-muted">{o ? `${usd(o.confirmed_month)} confirmed this month (${((o.progress_to_100k ?? 0) * 100).toFixed(3)}%)` : ""}</p>
        </CardBody>
      </Card>

      <Card className="mb-6">
        <CardHeader
          title="What each milestone takes"
          desc={m ? `Estimate based on ${m.basis}: $${m.effective_rpm}/1k qualified views, ${m.views_per_video.toLocaleString()} views per video, $${m.cost_per_video} per video.` : undefined}
          right={<Badge tone="info">estimate</Badge>}
        />
        <Table head={["Monthly revenue", "Qualified views", "Videos / month", "Videos / day", "Channels", "Operating cost", "Profit"]}>
          {m?.rows.map((r) => (
            <tr key={r.monthly_revenue}>
              <td className="tabular-nums">{usd(r.monthly_revenue)}</td>
              <td className="tabular-nums">{r.qualified_views_per_month.toLocaleString()}</td>
              <td className="tabular-nums">{r.videos_per_month.toLocaleString()}</td>
              <td className="tabular-nums">{r.videos_per_day}</td>
              <td className="tabular-nums">{r.channels_needed}</td>
              <td className="tabular-nums">{usd(r.operating_cost)}</td>
              <td className="tabular-nums">{usd(r.est_profit)}</td>
            </tr>
          ))}
        </Table>
      </Card>

      <div className="mb-6 grid gap-6 lg:grid-cols-2">
        {fin.data && (
          <>
            <SplitTable title="By stream" data={fin.data.breakdown.by_stream} />
            <SplitTable title="By campaign" data={fin.data.breakdown.by_campaign} />
            <SplitTable title="By platform" data={fin.data.breakdown.by_platform} />
            <SplitTable title="By account" data={fin.data.breakdown.by_account} />
          </>
        )}
      </div>

      <Card className="mb-6">
        <CardHeader title="Ledger" />
        {rev.data && rev.data.length === 0 ? (
          <Empty>No revenue recorded yet.</Empty>
        ) : (
          <Table head={["When", "Stream", "Amount", "Status", "Source", "Evidence", ""]}>
            {rev.data?.map((r) => (
              <tr key={r.id}>
                <td className="whitespace-nowrap text-muted">{fmtTime(r.occurred_at)}</td>
                <td>{r.stream}</td>
                <td className="tabular-nums">{usd(r.amount)} {r.currency !== "USD" ? r.currency : ""}</td>
                <td><Badge tone={r.status === "confirmed" ? "good" : r.status === "pending" ? "warn" : "bad"}>{r.status}</Badge></td>
                <td className="text-xs text-muted">{r.source}</td>
                <td className="max-w-xs text-xs text-muted">{r.evidence}</td>
                <td className="text-right">
                  {r.status === "pending" && (
                    <Button
                      size="sm"
                      onClick={() => {
                        const ev = window.prompt("Payout reference (e.g. Whop payout ID or bank statement line):");
                        if (ev) run(() => api(`/api/revenue/${r.id}/confirm`, { method: "POST", body: JSON.stringify({ evidence: ev }) }));
                      }}
                    >
                      Confirm paid
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </Table>
        )}
      </Card>

      <Card>
        <CardHeader title="Record money from a source without an API" desc="E.g. a Content Rewards payout round or a direct client invoice. Evidence is required." />
        <CardBody>
          <form
            className="grid gap-4 md:grid-cols-5 md:items-end"
            onSubmit={(e) => {
              e.preventDefault();
              run(() => api("/api/revenue", { method: "POST", body: JSON.stringify({ ...form, amount: Number(form.amount) }) }).then(() => setForm(EMPTY)));
            }}
          >
            <Field label="Stream">
              <Select value={form.stream} onChange={(e) => setForm({ ...form, stream: e.target.value })}>
                {["campaign", "youtube", "facebook", "instagram", "tiktok", "affiliate", "direct", "other"].map((x) => <option key={x}>{x}</option>)}
              </Select>
            </Field>
            <Field label="Amount ($)"><Input required type="number" step="0.01" min="0.01" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} /></Field>
            <Field label="Status">
              <Select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                <option value="pending">pending</option>
                <option value="confirmed">confirmed (paid)</option>
              </Select>
            </Field>
            <Field label="Reference"><Input required value={form.external_ref} onChange={(e) => setForm({ ...form, external_ref: e.target.value })} /></Field>
            <Field label="Evidence"><Input required minLength={6} value={form.evidence} onChange={(e) => setForm({ ...form, evidence: e.target.value })} /></Field>
            <div><Button type="submit">Record</Button></div>
          </form>
        </CardBody>
      </Card>
    </>
  );
}
