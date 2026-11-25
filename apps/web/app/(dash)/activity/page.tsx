"use client";

import { Card, Empty, ErrorNote, PageTitle, Table } from "@/components/ui";
import { useApi } from "@/lib/api";
import type { Decision } from "@/lib/types";
import { fmtTime } from "@/lib/utils";

export default function Activity() {
  const { data, error } = useApi<Decision[]>("/api/decisions?limit=200", 5000);
  return (
    <>
      <PageTitle title="Live activity" desc="Every decision the agents make, newest first. Refreshes every 5 seconds." />
      <ErrorNote error={error} />
      <Card>
        {data && data.length === 0 ? (
          <Empty>Nothing has happened yet. Start autopilot from the command center.</Empty>
        ) : (
          <Table head={["When", "Agent", "Decision", "Detail"]}>
            {data?.map((d) => (
              <tr key={d.id}>
                <td className="whitespace-nowrap text-muted">{fmtTime(d.at)}</td>
                <td className="whitespace-nowrap">{d.agent}</td>
                <td className="whitespace-nowrap text-accent">{d.action}</td>
                <td className="text-muted">{d.detail}</td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </>
  );
}
