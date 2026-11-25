"use client";

import { Badge, Card, Empty, ErrorNote, PageTitle, Table, statusTone } from "@/components/ui";
import { useApi } from "@/lib/api";
import type { ClipRow } from "@/lib/types";

export default function Library() {
  const { data, error } = useApi<ClipRow[]>("/api/clips?limit=300", 15000);
  return (
    <>
      <PageTitle title="Video library" desc="Clips the system has found and rendered. Previews appear here once the render engine (phase 2) produces files." />
      <ErrorNote error={error} />
      <Card>
        {data && data.length === 0 ? (
          <Empty>No clips yet. Clip finding and rendering arrive in phase 2.</Empty>
        ) : (
          <Table head={["Clip", "Title", "Range", "Score", "Stage", "Why chosen"]}>
            {data?.map((c) => (
              <tr key={c.id}>
                <td className="text-muted">#{c.id}</td>
                <td>{c.title || <span className="text-muted">untitled</span>}</td>
                <td className="whitespace-nowrap tabular-nums text-muted">{c.start_s.toFixed(1)}–{c.end_s.toFixed(1)}s</td>
                <td className="tabular-nums">{c.score.toFixed(2)}</td>
                <td><Badge tone={statusTone(c.stage)}>{c.stage}</Badge></td>
                <td className="text-xs text-muted">{c.reason}</td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </>
  );
}
