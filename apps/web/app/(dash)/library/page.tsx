"use client";

import { useState } from "react";

import { Badge, Card, CardBody, CardHeader, Empty, ErrorNote, PageTitle, Table, statusTone } from "@/components/ui";
import { API_URL, useApi } from "@/lib/api";
import type { ClipRow } from "@/lib/types";
import { usd } from "@/lib/utils";

function Detail({ c }: { c: ClipRow }) {
  const checks = c.qc?.checks ?? [];
  return (
    <div className="grid gap-6 md:grid-cols-[240px_1fr]">
      <div>
        {c.has_render ? (
          <video
            className="aspect-[9/16] w-full rounded-lg bg-black"
            controls
            preload="none"
            crossOrigin="use-credentials"
            poster={c.has_cover ? `${API_URL}/api/clips/${c.id}/cover` : undefined}
            src={`${API_URL}/api/clips/${c.id}/video`}
          />
        ) : (
          <div className="flex aspect-[9/16] w-full items-center justify-center rounded-lg border border-line text-sm text-muted">not rendered</div>
        )}
      </div>
      <div className="space-y-4 text-sm">
        <div>
          <div className="text-xs uppercase tracking-wide text-muted">Title</div>
          <div className="font-medium">{c.title || "not written yet"}</div>
        </div>
        {c.metadata && (
          <div>
            <div className="text-xs uppercase tracking-wide text-muted">Hook</div>
            <div>{c.metadata.hook}</div>
            <div className="mt-1 text-xs text-muted">
              Written by {c.metadata.writer}
              {c.metadata.model ? ` (${c.metadata.model})` : ""} · cost {usd(c.metadata.cost_usd)}
              {c.metadata.paid_promotion ? " · paid promotion disclosed" : ""}
              {c.metadata.notes.length ? ` · ${c.metadata.notes.join("; ")}` : ""}
            </div>
          </div>
        )}
        {c.description && (
          <div>
            <div className="text-xs uppercase tracking-wide text-muted">Description</div>
            <pre className="whitespace-pre-wrap font-sans">{c.description}</pre>
          </div>
        )}
        <div>
          <div className="text-xs uppercase tracking-wide text-muted">
            Quality control {c.qc_attempts ? `(attempt ${c.qc_attempts})` : ""}
          </div>
          {checks.length === 0 ? (
            <div className="text-muted">not checked yet</div>
          ) : (
            <ul className="mt-1 grid gap-1 sm:grid-cols-2">
              {checks.map((k) => (
                <li key={k.name} className="flex gap-2">
                  <Badge tone={k.passed ? "good" : "bad"}>{k.passed ? "pass" : "fail"}</Badge>
                  <span>{k.name.replace(/_/g, " ")}</span>
                  <span className="text-muted">{k.detail}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <div className="text-xs uppercase tracking-wide text-muted">Why this clip</div>
          <div className="text-muted">{c.reason}</div>
        </div>
      </div>
    </div>
  );
}

export default function Library() {
  const { data, error } = useApi<ClipRow[]>("/api/clips?limit=300", 15000);
  const [open, setOpen] = useState<number | null>(null);
  const selected = data?.find((c) => c.id === open);
  return (
    <>
      <PageTitle title="Video library" desc="Every clip the system found, with its render, quality-control results and the metadata it will publish with." />
      <ErrorNote error={error} />
      {selected && (
        <Card className="mb-6">
          <CardHeader title={`Clip #${selected.id}`} />
          <CardBody>
            <Detail c={selected} />
          </CardBody>
        </Card>
      )}
      <Card>
        {data && data.length === 0 ? (
          <Empty>No clips yet. They appear once an authorized source or campaign footage has been imported.</Empty>
        ) : (
          <Table head={["Clip", "Title", "Length", "Score", "QC", "Stage", ""]}>
            {data?.map((c) => (
              <tr key={c.id}>
                <td className="text-muted">#{c.id}{c.campaign_id ? " · paid" : ""}</td>
                <td>{c.title || <span className="text-muted">untitled</span>}</td>
                <td className="whitespace-nowrap tabular-nums text-muted">
                  {c.duration_s ? `${c.duration_s.toFixed(1)}s` : `${(c.end_s - c.start_s).toFixed(1)}s (planned)`}
                </td>
                <td className="tabular-nums">{c.score.toFixed(2)}</td>
                <td>{c.qc?.checks ? <Badge tone={c.qc.passed ? "good" : "bad"}>{c.qc.passed ? "passed" : "failed"}</Badge> : <span className="text-muted">–</span>}</td>
                <td><Badge tone={statusTone(c.stage)}>{c.stage}</Badge></td>
                <td>
                  <button className="text-sm hover:underline" onClick={() => setOpen(open === c.id ? null : c.id)}>
                    {open === c.id ? "Close" : "Details"}
                  </button>
                </td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </>
  );
}
