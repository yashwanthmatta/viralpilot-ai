"use client";

import { Badge, Card, ErrorNote, PageTitle, Table } from "@/components/ui";
import { useApi } from "@/lib/api";
import type { AgentRow } from "@/lib/types";
import { ago } from "@/lib/utils";

// The agent roster and the build phase each one ships in. Activity numbers
// come from the API; "not built yet" is stated plainly rather than faked.
const ROSTER: { name: string; role: string; phase: string; live: boolean }[] = [
  { name: "Trend Researcher", role: "Polls authorised sources on a schedule; trend signals arrive in phase 3", phase: "1 / 3", live: true },
  { name: "Content Acquisition Specialist", role: "Rights gate, de-duplication, safe download", phase: "1", live: true },
  { name: "Viral Clip Specialist", role: "Transcribe, find and rank moments", phase: "2", live: false },
  { name: "Professional Video Editor", role: "9:16 crop, captions, render", phase: "2", live: false },
  { name: "Audience Psychology Specialist", role: "Hooks and retention, no deceptive tactics", phase: "3", live: false },
  { name: "Quality Control Specialist", role: "Video, audio, captions, rights, policy checks", phase: "3", live: false },
  { name: "Social Media Manager", role: "Metadata and confirmed publishing via official APIs", phase: "1 / 4", live: true },
  { name: "Growth Analyst", role: "Metrics collection and strategy updates", phase: "5", live: false },
  { name: "Cost Optimization Specialist", role: "Budget reservations and hard limits", phase: "1", live: true },
  { name: "Autonomous Supervisor", role: "Scheduling, retries, crash recovery, heartbeat", phase: "1", live: true },
];

export default function Agents() {
  const { data, error } = useApi<AgentRow[]>("/api/agents", 15000);
  const byName = new Map((data ?? []).map((a) => [a.agent, a]));
  return (
    <>
      <PageTitle title="AI agents" desc="Structured workflows, not free-running chatbots. Most steps are deterministic and make no AI call." />
      <ErrorNote error={error} />
      <Card>
        <Table head={["Agent", "Responsibility", "Status", "Decisions", "Last active"]}>
          {ROSTER.map((a) => {
            const row = byName.get(a.name);
            return (
              <tr key={a.name}>
                <td className="whitespace-nowrap font-medium">{a.name}</td>
                <td className="text-muted">{a.role}</td>
                <td className="whitespace-nowrap">{a.live ? <Badge tone="good">active</Badge> : <Badge>phase {a.phase}</Badge>}</td>
                <td className="tabular-nums">{row?.decisions ?? 0}</td>
                <td className="whitespace-nowrap text-muted">{ago(row?.last_active)}</td>
              </tr>
            );
          })}
        </Table>
      </Card>
    </>
  );
}
