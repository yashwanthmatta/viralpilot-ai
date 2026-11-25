"use client";

import { Fragment, useState } from "react";

import { Badge, Button, Card, CardBody, CardHeader, Empty, ErrorNote, Field, Input, PageTitle, Select, Table } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import type { CampaignRow, SubmissionRow } from "@/lib/types";
import { fmtTime, usd } from "@/lib/utils";

const tone = (s: string) =>
  s === "active" || s === "eligible" ? "good" : s === "restricted" ? "warn" : s === "rejected" || s === "ended" || s === "exhausted" ? "bad" : "neutral";

const EMPTY = {
  provider: "content_rewards",
  external_id: "",
  name: "",
  url: "",
  payout_model: "cpm",
  rate_per_1k: "",
  flat_reward: "",
  min_payout: "",
  max_payout_per_video: "",
  budget_remaining: "",
  platform_fee_pct: "10",
  platforms: "youtube",
  requirements: "",
  footage_urls: "",
  ends_at: "",
};

const num = (v: string) => (v.trim() === "" ? null : Number(v));

export default function Campaigns() {
  const { data, error, reload } = useApi<CampaignRow[]>("/api/campaigns", 20000);
  const subs = useApi<SubmissionRow[]>("/api/submissions", 20000);
  const [form, setForm] = useState(EMPTY);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState<number | null>(null);

  async function run(fn: () => Promise<unknown>) {
    setErr(null);
    try {
      await fn();
      await Promise.all([reload(), subs.reload()]);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  const manual = (subs.data ?? []).filter((s) => s.status === "manual_required");

  return (
    <>
      <PageTitle
        title="Paid campaigns"
        desc="Found through the Whop API and any feeds you authorise, or added by you for marketplaces without an API. Expected profit is an estimate; money is tracked on the Revenue page."
      />
      <div className="space-y-6">
        <ErrorNote error={err || error} />

        {manual.length > 0 && (
          <Card className="border-warn/40">
            <CardHeader title={`${manual.length} clip link(s) to submit`} desc="These campaigns have no submission API. Paste each link on the campaign page, then mark it submitted." />
            <Table head={["Campaign", "Post", ""]}>
              {manual.map((s) => (
                <tr key={s.id}>
                  <td><a className="text-accent hover:underline" href={s.campaign_url} target="_blank" rel="noreferrer noopener">{s.campaign}</a></td>
                  <td className="break-all text-xs"><a className="hover:underline" href={s.post_url} target="_blank" rel="noreferrer noopener">{s.post_url}</a></td>
                  <td className="text-right">
                    <Button size="sm" onClick={() => run(() => api(`/api/submissions/${s.id}`, { method: "POST", body: JSON.stringify({ status: "submitted" }) }))}>Mark submitted</Button>
                  </td>
                </tr>
              ))}
            </Table>
          </Card>
        )}

        <Card>
          <CardHeader title="Opportunities, best expected profit first" />
          {data && data.length === 0 ? (
            <Empty>No campaigns yet. Connect Whop or add one below.</Empty>
          ) : (
            <Table head={["Campaign", "Pays", "Budget left", "Expected profit / clip", "Status", ""]}>
              {data?.map((c) => (
                <Fragment key={c.id}>
                  <tr>
                    <td>
                      <a className="hover:underline" href={c.url} target="_blank" rel="noreferrer noopener">{c.name}</a>
                      <div className="text-xs text-muted">{c.provider} · {c.platforms.join(", ") || "any platform"} · submit: {c.submission_method}</div>
                    </td>
                    <td className="whitespace-nowrap tabular-nums">
                      {c.payout_model === "cpm" ? `${usd(c.rate_per_1k ?? 0)}/1k views` : `${usd(c.flat_reward ?? 0)} per clip`}
                      {c.max_payout_per_video ? <div className="text-xs text-muted">max {usd(c.max_payout_per_video)}</div> : null}
                    </td>
                    <td className="tabular-nums">{c.budget_remaining != null ? usd(c.budget_remaining) : "–"}</td>
                    <td className="tabular-nums">
                      {c.evaluation?.expected_profit != null ? (
                        <span title="estimate">{usd(c.evaluation.expected_profit)} <span className="text-xs text-muted">est.</span></span>
                      ) : "–"}
                    </td>
                    <td>
                      <Badge tone={tone(c.status)}>{c.status}</Badge>
                      <div className="mt-1 max-w-xs text-xs text-muted">{c.status_reason}</div>
                    </td>
                    <td className="space-x-1 whitespace-nowrap text-right">
                      <Button size="sm" variant="ghost" onClick={() => setOpen(open === c.id ? null : c.id)}>Details</Button>
                      {c.status !== "restricted" && <Button size="sm" onClick={() => run(() => api(`/api/campaigns/${c.id}/pause`, { method: "POST" }))}>Pause</Button>}
                      {c.status === "restricted" && <Button size="sm" onClick={() => run(() => api(`/api/campaigns/${c.id}/reassess`, { method: "POST" }))}>Re-check</Button>}
                    </td>
                  </tr>
                  {open === c.id && (
                    <tr key={`${c.id}-d`}>
                      <td colSpan={6} className="bg-panel-2/40 text-xs text-muted">
                        <div className="grid gap-3 md:grid-cols-2">
                          <div>
                            <div className="mb-1 text-fg">Estimate breakdown</div>
                            {c.evaluation?.expected_payout != null && (
                              <ul className="space-y-0.5">
                                <li>Expected payout per clip before risk: {usd(c.evaluation.expected_payout ?? 0)}</li>
                                <li>Chance a clip reaches the minimum payout: {Math.round((c.evaluation.p_reach_min ?? 0) * 100)}%</li>
                                <li>Approval × payment probability: {c.evaluation.p_approval} × {c.evaluation.p_payment}; fee {Math.round((c.evaluation.fee_pct ?? 0) * 100)}%</li>
                                <li>Production cost: {usd(c.evaluation.production_cost ?? 0)} · clips the budget can pay: {c.evaluation.clips_affordable ?? "–"}</li>
                                <li>Views model: {c.evaluation.view_model}</li>
                                {(c.evaluation.assumptions ?? []).map((a) => <li key={a}>Assumption: {a}</li>)}
                              </ul>
                            )}
                          </div>
                          <div>
                            <div className="mb-1 text-fg">Requirements</div>
                            <p className="whitespace-pre-wrap">{c.requirements}</p>
                            <div className="mt-2">Ends: {fmtTime(c.ends_at)} · Footage links: {c.footage_urls.length}</div>
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </Table>
          )}
        </Card>

        <Card>
          <CardHeader title="Add a campaign" desc="For Content Rewards, Vyro, direct deals and anything else without an API. Copy the terms exactly as the campaign states them." />
          <CardBody>
            <form
              className="grid gap-4 md:grid-cols-3"
              onSubmit={(e) => {
                e.preventDefault();
                run(() =>
                  api("/api/campaigns", {
                    method: "POST",
                    body: JSON.stringify({
                      provider: form.provider,
                      external_id: form.external_id || form.url,
                      name: form.name,
                      url: form.url,
                      payout_model: form.payout_model,
                      rate_per_1k: num(form.rate_per_1k),
                      flat_reward: num(form.flat_reward),
                      min_payout: num(form.min_payout),
                      max_payout_per_video: num(form.max_payout_per_video),
                      budget_remaining: num(form.budget_remaining),
                      platform_fee_pct: (num(form.platform_fee_pct) ?? 0) / 100,
                      platforms: form.platforms.split(",").map((p) => p.trim()).filter(Boolean),
                      requirements: form.requirements,
                      footage_urls: form.footage_urls.split(/\s+/).filter(Boolean),
                      ends_at: form.ends_at || null,
                    }),
                  }).then(() => setForm(EMPTY)),
                );
              }}
            >
              <Field label="Marketplace">
                <Select value={form.provider} onChange={(e) => setForm({ ...form, provider: e.target.value })}>
                  {["content_rewards", "vyro", "direct", "whop_manual", "other"].map((p) => <option key={p}>{p}</option>)}
                </Select>
              </Field>
              <Field label="Campaign name"><Input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
              <Field label="Campaign link (https)"><Input required type="url" value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} /></Field>
              <Field label="Pays by">
                <Select value={form.payout_model} onChange={(e) => setForm({ ...form, payout_model: e.target.value })}>
                  <option value="cpm">per 1,000 views</option>
                  <option value="flat">flat per clip</option>
                </Select>
              </Field>
              {form.payout_model === "cpm" ? (
                <Field label="$ per 1,000 views"><Input type="number" step="0.01" value={form.rate_per_1k} onChange={(e) => setForm({ ...form, rate_per_1k: e.target.value })} /></Field>
              ) : (
                <Field label="$ per approved clip"><Input type="number" step="0.01" value={form.flat_reward} onChange={(e) => setForm({ ...form, flat_reward: e.target.value })} /></Field>
              )}
              <Field label="Budget remaining ($)"><Input type="number" step="0.01" value={form.budget_remaining} onChange={(e) => setForm({ ...form, budget_remaining: e.target.value })} /></Field>
              <Field label="Minimum payout ($)"><Input type="number" step="0.01" value={form.min_payout} onChange={(e) => setForm({ ...form, min_payout: e.target.value })} /></Field>
              <Field label="Max payout per video ($)"><Input type="number" step="0.01" value={form.max_payout_per_video} onChange={(e) => setForm({ ...form, max_payout_per_video: e.target.value })} /></Field>
              <Field label="Platform fee (%)"><Input type="number" step="0.1" value={form.platform_fee_pct} onChange={(e) => setForm({ ...form, platform_fee_pct: e.target.value })} /></Field>
              <Field label="Platforms (comma separated)"><Input value={form.platforms} onChange={(e) => setForm({ ...form, platforms: e.target.value })} /></Field>
              <Field label="Ends (optional)"><Input type="datetime-local" value={form.ends_at} onChange={(e) => setForm({ ...form, ends_at: e.target.value })} /></Field>
              <Field label="Footage links (direct files or feeds)" hint="Space separated. Only footage the campaign provides."><Input value={form.footage_urls} onChange={(e) => setForm({ ...form, footage_urls: e.target.value })} /></Field>
              <div className="md:col-span-3">
                <Field label="Requirements (copy exactly)">
                  <textarea required className="min-h-24 w-full rounded-md border border-line bg-bg p-3 text-sm outline-none focus:border-accent/60" value={form.requirements} onChange={(e) => setForm({ ...form, requirements: e.target.value })} />
                </Field>
              </div>
              <div><Button type="submit">Add and evaluate</Button></div>
            </form>
          </CardBody>
        </Card>
      </div>
    </>
  );
}
