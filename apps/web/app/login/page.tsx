"use client";

import { Gauge } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button, Card, ErrorNote, Input } from "@/components/ui";
import { api } from "@/lib/api";

export default function Login() {
  const router = useRouter();
  const [pw, setPw] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <div className="grid min-h-screen place-items-center px-4">
      <Card className="w-full max-w-sm p-6">
        <div className="mb-6 flex items-center gap-2">
          <div className="grid h-8 w-8 place-items-center rounded-md bg-accent/15 text-accent">
            <Gauge size={18} />
          </div>
          <div>
            <div className="text-sm font-semibold">ViralPilot</div>
            <div className="text-xs text-muted">Owner sign-in</div>
          </div>
        </div>
        <form
          className="space-y-3"
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            setErr(null);
            try {
              await api("/api/auth/login", { method: "POST", body: JSON.stringify({ password: pw }) });
              router.push("/");
            } catch (e) {
              setErr(e instanceof Error ? e.message : String(e));
            } finally {
              setBusy(false);
            }
          }}
        >
          <Input type="password" autoComplete="current-password" placeholder="Password" value={pw} onChange={(e) => setPw(e.target.value)} autoFocus />
          <ErrorNote error={err} />
          <Button type="submit" className="w-full" disabled={busy || !pw}>
            {busy ? "Signing in…" : "Sign in"}
          </Button>
        </form>
      </Card>
    </div>
  );
}
