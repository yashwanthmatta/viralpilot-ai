"use client";

import { Card, CardBody, CardHeader, Empty, ErrorNote, PageTitle, Table } from "@/components/ui";
import { useApi } from "@/lib/api";
import type { Audit } from "@/lib/types";
import { fmtTime } from "@/lib/utils";

export default function Security() {
  const { data, error } = useApi<Audit[]>("/api/audit?limit=200", 30000);
  return (
    <>
      <PageTitle title="Account & security" desc="Sign-ins and every change to autopilot, sources, accounts and limits." />
      <ErrorNote error={error} />
      <div className="space-y-6">
        <Card>
          <CardHeader title="How access works" />
          <CardBody className="space-y-1.5 text-sm text-muted">
            <p>Single owner account. The password is stored only as an argon2 hash in the server&apos;s environment.</p>
            <p>To change it, run <code className="text-fg">python scripts/hash_password.py</code> and update ADMIN_PASSWORD_HASH on the host. Rotating SECRET_KEY signs everyone out.</p>
            <p>Platform tokens are encrypted with CREDENTIALS_KEY and never shown in the dashboard.</p>
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="Audit log" />
          {data && data.length === 0 ? (
            <Empty>No events.</Empty>
          ) : (
            <Table head={["When", "Action", "Detail", "IP"]}>
              {data?.map((a, i) => (
                <tr key={i}>
                  <td className="whitespace-nowrap text-muted">{fmtTime(a.at)}</td>
                  <td>{a.action}</td>
                  <td className="text-xs text-muted">{a.detail}</td>
                  <td className="text-xs text-muted">{a.ip}</td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
      </div>
    </>
  );
}
