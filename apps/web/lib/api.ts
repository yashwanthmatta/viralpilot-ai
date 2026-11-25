"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers: Record<string, string> = { ...(init.headers as Record<string, string> | undefined) };
  if (init.body) headers["content-type"] = "application/json";
  // Required by the API on every state-changing request (CSRF defence).
  if (method !== "GET") headers["x-vp-csrf"] = "1";
  const res = await fetch(`${API_URL}${path}`, { ...init, method, headers, credentials: "include", cache: "no-store" });
  if (res.status === 401 && typeof window !== "undefined" && !path.startsWith("/api/auth")) {
    // Full reload on purpose: drops all in-memory state after the session ends.
    window.location.href = "/login"; // eslint-disable-line @next/next/no-location-assign-relative-destination
  }
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}

/** Fetch and poll. Every value the dashboard shows comes through here from the API. */
export function useApi<T>(path: string, intervalMs = 15000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const alive = useRef(true);
  const load = useCallback(async () => {
    try {
      const d = await api<T>(path);
      if (alive.current) {
        setData(d);
        setError(null);
      }
    } catch (e) {
      if (alive.current) setError(e instanceof Error ? e.message : String(e));
    }
  }, [path]);
  useEffect(() => {
    alive.current = true;
    const first = setTimeout(load, 0);
    const t = setInterval(load, intervalMs);
    return () => {
      alive.current = false;
      clearTimeout(first);
      clearInterval(t);
    };
  }, [load, intervalMs]);
  return { data, error, reload: load };
}
