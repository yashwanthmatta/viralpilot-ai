"use client";

import { Badge, Card, CardHeader, Empty, ErrorNote, PageTitle, Stat, Table } from "@/components/ui";
import { useApi } from "@/lib/api";
import type { Costs, Status } from "@/lib/types";
import { fmtTime, usd } from "@/lib/utils";

export default function CostsPage() {
  const costs = useApi<Costs>("/api/costs?limit=300", 30000);
  const st = useApi<Status>("/api/status", 30000);
  const cats = Object.entries(costs.data?.by_category ?? {});
  return (
    <>
      <PageTitle title="Costs" desc="Every paid step reserves its cost before running, against daily, monthly, lifetime and per-video caps. Revenue lives on the Revenue page." />
      <ErrorNote error={costs.error || st.error} />
      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Spent today" value={st.data ? usd(st.data.spend.today) : "–"} hint={st.data ? `limit ${usd(st.data.spend.daily_limit)}` : undefined} />
        <Stat label="Spent this month" value={st.data ? usd(st.data.spend.month) : "–"} hint={st.data ? `limit ${usd(st.data.spend.monthly_limit)}` : undefined} />
        <Stat label="Lifetime spend" value={st.data ? usd(st.data.spend.total) : "–"} hint={st.data ? `cap ${usd(st.data.spend.total_limit)}` : undefined} />
        <Stat label="Net this month" value={st.data ? usd(st.data.revenue.net_month_confirmed) : "–"} hint="confirmed revenue minus spend" />
      </div>
      <div className="space-y-6">
        <Card>
          <CardHeader title="By category (all time)" />
          {cats.length === 0 ? (
            <Empty>No spending recorded.</Empty>
          ) : (
            <Table head={["Category", "Total"]}>
              {cats.map(([k, v]) => (
                <tr key={k}><td>{k}</td><td className="tabular-nums">{usd(v)}</td></tr>
              ))}
            </Table>
          )}
        </Card>
        <Card>
          <CardHeader title="Ledger" />
          {costs.data && costs.data.entries.length === 0 ? (
            <Empty>No entries.</Empty>
          ) : (
            <Table head={["When", "Category", "Amount", "Status", "What"]}>
              {costs.data?.entries.map((e) => (
                <tr key={e.id}>
                  <td className="whitespace-nowrap text-muted">{fmtTime(e.at)}</td>
                  <td>{e.category}</td>
                  <td className="tabular-nums">{usd(e.usd)}</td>
                  <td><Badge tone={e.status === "released" ? "neutral" : e.status === "committed" ? "good" : "info"}>{e.status}</Badge></td>
                  <td className="text-xs text-muted">{e.description}</td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
      </div>
    </>
  );
}
