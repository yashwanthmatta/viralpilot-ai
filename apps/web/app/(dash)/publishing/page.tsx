"use client";

import { Badge, Card, CardHeader, Empty, ErrorNote, PageTitle, Table, statusTone } from "@/components/ui";
import { useApi } from "@/lib/api";
import type { Pub } from "@/lib/types";
import { fmtTime } from "@/lib/utils";

export default function Publishing() {
  const { data, error } = useApi<Pub[]>("/api/publications?limit=300", 15000);
  const upcoming = (data ?? []).filter((p) => p.status === "scheduled").sort((a, b) => (a.scheduled_for ?? "").localeCompare(b.scheduled_for ?? ""));
  return (
    <>
      <PageTitle title="Publishing" desc="A video counts as published only when the platform returns its own post ID." />
      <ErrorNote error={error} />
      <div className="space-y-6">
        <Card>
          <CardHeader title="Content calendar" desc="Scheduled posts, soonest first." />
          {upcoming.length === 0 ? (
            <Empty>Nothing scheduled.</Empty>
          ) : (
            <Table head={["When", "Platform", "Clip"]}>
              {upcoming.map((p) => (
                <tr key={p.id}>
                  <td>{fmtTime(p.scheduled_for)}</td>
                  <td>{p.platform}</td>
                  <td className="text-muted">#{p.clip_id}</td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
        <Card>
          <CardHeader title="History" />
          {data && data.length === 0 ? (
            <Empty>No publishing attempts yet.</Empty>
          ) : (
            <Table head={["Clip", "Platform", "Status", "Confirmed", "Post", "Note"]}>
              {data?.map((p) => (
                <tr key={p.id}>
                  <td className="text-muted">#{p.clip_id}</td>
                  <td>{p.platform}</td>
                  <td><Badge tone={statusTone(p.status)}>{p.status}</Badge></td>
                  <td className="whitespace-nowrap text-muted">{p.confirmed_at ? fmtTime(p.confirmed_at) : "–"}</td>
                  <td>{p.url ? <a className="text-accent hover:underline" href={p.url} target="_blank" rel="noreferrer noopener">{p.platform_post_id}</a> : "–"}</td>
                  <td className="text-xs text-muted">{p.error}</td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
      </div>
    </>
  );
}
