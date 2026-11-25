"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { Badge, Button, Card, CardBody, CardHeader, Empty, ErrorNote, Field, Input, PageTitle, Select, Table } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import type { Account, Platform } from "@/lib/types";

function AccountsInner() {
  const accounts = useApi<Account[]>("/api/accounts", 30000);
  const platforms = useApi<Platform[]>("/api/platforms", 60000);
  const [form, setForm] = useState({ platform: "youtube", display_name: "", max_posts_per_day: 1, publishing_allowed: false });
  const [err, setErr] = useState<string | null>(null);
  const params = useSearchParams();
  const oauthError = params.get("error");
  const connected = params.get("connected");
  const note = connected ? `${connected} connected. Turn on "Allow publishing" when you're ready for autopilot to post there.` : null;

  async function connect(platform: string) {
    setErr(null);
    try {
      const r = await api<{ url: string }>(`/api/oauth/${platform}/start`, { method: "POST" });
      window.location.assign(r.url);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

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
        <ErrorNote error={err || oauthError || accounts.error} />
        {note && <div className="rounded-lg border border-line bg-panel px-4 py-3 text-sm text-go">{note}</div>}
        <Card>
          <CardHeader title="Platform status" desc="What each official API allows this app to do today." />
          <Table head={["Platform", "Autonomous publishing", "Why", ""]}>
            {platforms.data?.map((p) => (
              <tr key={p.platform}>
                <td className="capitalize">{p.platform}</td>
                <td>{p.available ? <Badge tone="good">available</Badge> : <Badge tone="warn">blocked</Badge>}</td>
                <td className="text-xs text-muted">{p.reason}</td>
                <td className="text-right">
                  {p.oauth && p.available && (
                    <Button size="sm" onClick={() => connect(p.platform)}>Connect {p.platform === "youtube" ? "YouTube" : p.platform}</Button>
                  )}
                </td>
              </tr>
            ))}
          </Table>
        </Card>

        <Card>
          <CardHeader title="Connected accounts" desc="Connect through the platform's own sign-in. Tokens are stored encrypted; autopilot posts only where you allow it." />
          {accounts.data && accounts.data.length === 0 ? (
            <Empty>No accounts yet.</Empty>
          ) : (
            <Table head={["Platform", "Name", "OAuth", "Autopilot may publish", "Posts/day", ""]}>
              {accounts.data?.map((a) => (
                <tr key={a.id}>
                  <td className="capitalize">{a.platform}</td>
                  <td>{a.name || "–"}</td>
                  <td>
                    {a.connected ? <Badge tone={a.health === "paused" ? "bad" : "good"}>{a.health === "paused" ? "needs attention" : "connected"}</Badge> : <Badge>not connected</Badge>}
                    {(a.health_note || (!a.can_publish && a.blocked_reason)) && (
                      <div className="mt-1 max-w-xs text-xs text-muted">{a.health_note || a.blocked_reason}</div>
                    )}
                  </td>
                  <td>{a.publishing_allowed ? <Badge tone="good">allowed</Badge> : <Badge>not allowed</Badge>}</td>
                  <td className="tabular-nums">{a.max_posts_per_day}</td>
                  <td className="space-x-2 whitespace-nowrap text-right">
                    {a.oauth && (!a.connected || a.health === "paused") && (
                      <Button size="sm" onClick={() => connect(a.platform)}>{a.connected ? "Reconnect" : "Connect"}</Button>
                    )}
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

export default function Accounts() {
  return (
    <Suspense>
      <AccountsInner />
    </Suspense>
  );
}
