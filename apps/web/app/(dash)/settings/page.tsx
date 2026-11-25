"use client";

import { useEffect, useState } from "react";

import { Button, Card, CardBody, CardHeader, ErrorNote, Field, Input, PageTitle } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import type { Budget } from "@/lib/types";

export default function Settings() {
  const { data, error, reload } = useApi<Budget>("/api/budget", 60000);
  const [form, setForm] = useState<Budget | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (data && !form) setForm(data); // eslint-disable-line react-hooks/set-state-in-effect
  }, [data, form]);

  return (
    <>
      <PageTitle title="Settings" desc="Spending limits are hard ceilings: paid work stops when one is reached and resumes when the period resets." />
      <ErrorNote error={err || error} />
      <Card className="max-w-2xl">
        <CardHeader title="Budget and output" />
        <CardBody>
          {form && (
            <form
              className="grid gap-4 md:grid-cols-2"
              onSubmit={async (e) => {
                e.preventDefault();
                setErr(null);
                setMsg(null);
                try {
                  await api("/api/budget", { method: "PUT", body: JSON.stringify(form) });
                  setMsg("Saved.");
                  await reload();
                } catch (e) {
                  setErr(e instanceof Error ? e.message : String(e));
                }
              }}
            >
              <Field label="Daily limit (USD)">
                <Input type="number" step="0.01" min={0} value={form.daily_limit_usd} onChange={(e) => setForm({ ...form, daily_limit_usd: Number(e.target.value) })} />
              </Field>
              <Field label="Monthly limit (USD)">
                <Input type="number" step="0.01" min={0} value={form.monthly_limit_usd} onChange={(e) => setForm({ ...form, monthly_limit_usd: Number(e.target.value) })} />
              </Field>
              <Field label="Per-video limit (USD)" hint="A single video that would cost more is abandoned.">
                <Input type="number" step="0.01" min={0} value={form.per_item_limit_usd} onChange={(e) => setForm({ ...form, per_item_limit_usd: Number(e.target.value) })} />
              </Field>
              <Field label="Unique videos per day" hint="Spread across eligible platforms.">
                <Input type="number" min={0} max={50} value={form.max_videos_per_day} onChange={(e) => setForm({ ...form, max_videos_per_day: Number(e.target.value) })} />
              </Field>
              <div className="flex items-center gap-3 md:col-span-2">
                <Button type="submit">Save limits</Button>
                {msg && <span className="text-sm text-go">{msg}</span>}
              </div>
            </form>
          )}
        </CardBody>
      </Card>
    </>
  );
}
