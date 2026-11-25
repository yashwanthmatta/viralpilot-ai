"use client";

import { Badge, Card, Empty, ErrorNote, PageTitle, Table, statusTone } from "@/components/ui";
import { useApi } from "@/lib/api";
import type { Item } from "@/lib/types";
import { fmtTime } from "@/lib/utils";

export default function Discovery() {
  const { data, error } = useApi<Item[]>("/api/content?limit=300", 15000);
  return (
    <>
      <PageTitle title="Content discovery" desc="Everything found in your authorised sources, with the rights decision for each item." />
      <ErrorNote error={error} />
      <Card>
        {data && data.length === 0 ? (
          <Empty>No content discovered yet. Add a source and start autopilot.</Empty>
        ) : (
          <Table head={["Found", "Title", "Stage", "Licence", "Rights decision"]}>
            {data?.map((i) => (
              <tr key={i.id}>
                <td className="whitespace-nowrap text-muted">{fmtTime(i.discovered_at)}</td>
                <td>{i.title || <span className="text-muted">untitled</span>}</td>
                <td><Badge tone={statusTone(i.stage)}>{i.stage}</Badge></td>
                <td className="whitespace-nowrap text-muted">{i.license}</td>
                <td className="text-xs text-muted">{i.rights_note}</td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </>
  );
}
