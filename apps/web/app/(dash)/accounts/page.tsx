"use client";

import { useState } from "react";

import { Badge, Button, Card, CardBody, CardHeader, Empty, ErrorNote, Field, Input, PageTitle, Select, Table } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import type { Account, Platform } from "@/lib/types";

export default function Accounts() {
  const accounts = useApi<Account[]>("/api/accounts", 30000);
  const platforms = useApi<Platform[]>("/api/platforms", 60000);
  const [form, setForm] = useState({ platform: "youtube", display_name: "", max_posts_per_day: 1, publishing_allowed: false });
  const [err, setErr] = useState<string | null>(null);

  async function run(fn: () => Promise<unknown>) {
    setErr(null);
    try {
      await fn();
      await accounts.reload();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <>
      <PageTitle title="Social accounts" desc="Autopilot only publishes to accounts you have allowed, and only where the platform permits it." />
      <div className="space-y-6">
        <ErrorNote error={err || accounts.error} />
        <Card>
          <CardHeader title="Platform status" desc="What each official API allows this app to do today." />
          <Table head={["Platform", "Autonomous publishing", "Why"]}>
            {platforms.data?.map((p) => (
              <tr key={p.platform}>
                <td className="capitalize">{p.platform}</td>
                <td>{p.available ? <Badge tone="good">available</Badge> : <Badge tone="warn">blocked</Badge>}</td>
                <td className="text-xs text-muted">{p.reason}</td>
              </tr>
            ))}
          </Table>
        </Card>

        <Card>
          <CardHeader title="Connected accounts" desc="OAuth sign-in for each platform ships with its publishing adapter (phase 4)." />
          {accounts.data && accounts.data.length === 0 ? (
            <Empty>No accounts yet.</Empty>
          ) : (
            <Table head={["Platform", "Name", "OAuth", "Autopilot may publish", "Posts/day", ""]}>
              {accounts.data?.map((a) => (
                <tr key={a.id}>
                  <td className="capitalize">{a.platform}</td>
                  <td>{a.name || "–"}</td>
                  <td>{a.connected ? <Badge tone="good">connected</Badge> : <Badge>not connected</Badge>}</td>
                  <td>{a.publishing_allowed ? <Badge tone="good">allowed</Badge> : <Badge>not allowed</Badge>}</td>
                  <td className="tabular-nums">{a.max_posts_per_day}</td>
                  <td className="text-right">
                    <Button size="sm" onClick={() => run(() => api(`/api/accounts/${a.id}`, { method: "PATCH", body: JSON.stringify({ publishing_allowed: !a.publishing_allowed }) }))}>
                      {a.publishing_allowed ? "Revoke permission" : "Allow publishing"}
                    </Button>
                  </td>
                </tr>
              ))}
            </Table>
          )}
          <CardBody className="border-t border-line">
            <form
              className="grid gap-3 md:grid-cols-5 md:items-end"
              onSubmit={(e) => {
                e.preventDefault();
                run(() => api("/api/accounts", { method: "POST", body: JSON.stringify(form) }));
              }}
            >
              <Field label="Platform">
                <Select value={form.platform} onChange={(e) => setForm({ ...form, platform: e.target.value })}>
                  {["youtube", "tiktok", "instagram", "facebook"].map((p) => <option key={p}>{p}</option>)}
                </Select>
              </Field>
              <Field label="Account name">
                <Input value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} />
              </Field>
              <Field label="Max posts per day">
                <Input type="number" min={0} max={20} value={form.max_posts_per_day} onChange={(e) => setForm({ ...form, max_posts_per_day: Number(e.target.value) })} />
              </Field>
              <label className="flex h-9 items-center gap-2 text-sm">
                <input type="checkbox" checked={form.publishing_allowed} onChange={(e) => setForm({ ...form, publishing_allowed: e.target.checked })} />
                Allow autopilot to publish
              </label>
              <Button type="submit">Add account</Button>
            </form>
          </CardBody>
        </Card>
      </div>
    </>
  );
}
