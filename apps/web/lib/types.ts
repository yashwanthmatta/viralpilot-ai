export type CountKey =
  | "discovered"
  | "rights_rejected"
  | "imported"
  | "analyzed"
  | "clips"
  | "editing"
  | "scheduled"
  | "published"
  | "publish_blocked"
  | "total_views"
  | "jobs_pending"
  | "jobs_running"
  | "jobs_blocked"
  | "jobs_failed"
  | "errors_auto_recovered";

export type Status = {
  autopilot: { enabled: boolean; reason: string; changed_at: string | null; last_tick_at: string | null; supervisor_stale: boolean };
  counts: Record<CountKey, number>;
  spend: { today: number; daily_limit: number; month: number; monthly_limit: number; per_video_limit: number; max_videos_per_day: number };
  revenue: number | null;
  blockers: { key: string; title: string; detail: string; since: string | null }[];
  upcoming: { id: number; platform: string; clip_id: number; at: string }[];
};
export type Decision = { id: number; at: string; agent: string; action: string; detail: string; item_id: number | null; clip_id: number | null };
export type AgentRow = { agent: string; decisions: number; last_active: string | null };
export type Item = { id: number; title: string; stage: string; license: string; rights_note: string; source_id: number | null; discovered_at: string };
export type ClipRow = { id: number; item_id: number; start_s: number; end_s: number; score: number; stage: string; title: string; reason: string; has_render: boolean };
export type Pub = { id: number; clip_id: number; platform: string; status: string; scheduled_for: string | null; confirmed_at: string | null; platform_post_id: string; url: string; error: string };
export type SourceRow = { id: number; name: string; kind: string; url: string; license: string; rights_evidence: string; attribution: string; niche: string; enabled: boolean; last_polled_at: string | null };
export type Account = { id: number; platform: string; name: string; connected: boolean; publishing_allowed: boolean; max_posts_per_day: number; can_publish: boolean; blocked_reason: string };
export type Platform = { platform: string; available: boolean; reason: string };
export type JobRow = { id: number; kind: string; status: string; attempts: number; max_attempts: number; run_after: string; last_error: string; created_at: string };
export type Budget = { daily_limit_usd: number; monthly_limit_usd: number; per_item_limit_usd: number; max_videos_per_day: number };
export type Costs = {
  by_category: Record<string, number>;
  entries: { id: number; at: string; category: string; usd: number; status: string; description: string; item_id: number | null }[];
};
export type Audit = { at: string; action: string; detail: string; ip: string };
