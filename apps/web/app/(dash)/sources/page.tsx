"use client";

import { useState } from "react";

import { Badge, Button, Card, CardBody, CardHeader, Empty, ErrorNote, Field, Input, PageTitle, Select, Table } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import type { SourceRow } from "@/lib/types";
import { ago } from "@/lib/utils";

const LICENSES = [
  ["user_owned", "I own this content"],
  ["creator_authorized", "Creator gave written permission"],
  ["cc_by", "Creative Commons BY (credit required)"],
  ["cc_by_sa", "Creative Commons BY-SA (credit required)"],
  ["cc0", "CC0"],
  ["public_domain", "Public domain"],
  ["licensed_library", "Commercially licensed library"],
] as const;

const EMPTY = { name: "", url: "", license_type: "user_owned", rights_evidence: "", attribution: "", niche: "" };

export default function Sources() {
  const { data, error, reload } = useApi<SourceRow[]>("/api/sources", 30000);
  const [form, setForm] = useState(EMPTY);
  const [err, setErr] = useState<string | null>(null);

  async function run(fn: () => Promise<unknown>, reset = false) {
    setErr(null);
    try {
      await fn();
      if (reset) setForm(EMPTY);
      await reload();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <>
      <PageTitle
        title="Authorised sources"
        desc="Only content you own or that is licensed for commercial reuse. Non-commercial (NC), no-derivatives (ND) and unclear licences are always rejected."
      />
      <div className="space-y-6">
        <ErrorNote error={err || error} />
        <Card>
          {data && data.length === 0 ? (
            <Empty>No sources yet. Add one below.</Empty>
          ) : (
            <Table head={["Name", "Licence", "Evidence", "Last polled", "Status", ""]}>
              {data?.map((s) => (
                <tr key={s.id}>
                  <td>
                    <div>{s.name}</div>
                    <div className="text-xs text-muted break-all">{s.url}</div>
                  </td>
                  <td className="whitespace-nowrap text-muted">{s.license}</td>
                  <td className="text-xs text-muted">{s.rights_evidence}</td>
                  <td className="whitespace-nowrap text-muted">{ago(s.last_polled_at)}</td>
                  <td>{s.enabled ? <Badge tone="good">on</Badge> : <Badge>off</Badge>}</td>
                  <td className="text-right">
                    <Button size="sm" onClick={() => run(() => api(`/api/sources/${s.id}/toggle`, { method: "POST" }))}>
                      {s.enabled ? "Disable" : "Enable"}
                    </Button>
                  </td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
        <Card>
          <CardHeader title="Add a source" desc="RSS or Atom feeds with audio/video enclosures (podcasts, your own channel's feed, Internet Archive collections)." />
          <CardBody>
            <form
              className="grid gap-4 md:grid-cols-2"
              onSubmit={(e) => {
                e.preventDefault();
                run(() => api("/api/sources", { method: "POST", body: JSON.stringify({ ...form, kind: "rss" }) }), true);
              }}
            >
              <Field label="Name"><Input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
              <Field label="Feed URL (https)"><Input required type="url" value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} /></Field>
              <Field label="Licence">
                <Select value={form.license_type} onChange={(e) => setForm({ ...form, license_type: e.target.value })}>
                  {LICENSES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </Select>
              </Field>
              <Field label="Rights evidence" hint="Licence URL, permission reference, or a statement that you own it.">
                <Input required value={form.rights_evidence} onChange={(e) => setForm({ ...form, rights_evidence: e.target.value })} />
              </Field>
              <Field label="Attribution" hint="Required for CC BY and CC BY-SA.">
                <Input value={form.attribution} onChange={(e) => setForm({ ...form, attribution: e.target.value })} />
              </Field>
              <Field label="Niche (optional)"><Input value={form.niche} onChange={(e) => setForm({ ...form, niche: e.target.value })} /></Field>
              <div className="md:col-span-2"><Button type="submit">Authorise source</Button></div>
            </form>
          </CardBody>
        </Card>
      </div>
    </>
  );
}
