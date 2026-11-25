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
  spend: { today: number; daily_limit: number; month: number; monthly_limit: number; per_video_limit: number; max_videos_per_day: number; total: number; total_limit: number };
  revenue: {
    confirmed_today: number;
    confirmed_month: number;
    pending: number;
    net_month_confirmed: number;
    progress_to_100k: number;
    next_milestone: number | null;
    active_campaigns: number;
  };
  blockers: { key: string; title: string; detail: string; since: string | null }[];
  upcoming: { id: number; platform: string; clip_id: number; at: string }[];
};
export type Decision = { id: number; at: string; agent: string; action: string; detail: string; item_id: number | null; clip_id: number | null };
export type AgentRow = { agent: string; decisions: number; last_active: string | null };
export type Item = { id: number; title: string; stage: string; license: string; rights_note: string; source_id: number | null; discovered_at: string };
export type QCCheck = { name: string; passed: boolean; detail: string; retryable: boolean };
export type ClipMeta = { hook: string; writer: string; model: string; cost_usd: number; paid_promotion: boolean; notes: string[] };
export type ClipRow = {
  id: number; item_id: number; start_s: number; end_s: number; score: number; stage: string; title: string; reason: string;
  qc: { passed?: boolean; checks?: QCCheck[] }; qc_attempts: number; description: string; hashtags: string[];
  metadata: ClipMeta | null; campaign_id: number | null; duration_s: number | null; has_render: boolean; has_cover: boolean;
};
export type Pub = { id: number; clip_id: number; platform: string; status: string; scheduled_for: string | null; confirmed_at: string | null; platform_post_id: string; url: string; error: string };
export type SourceRow = { id: number; name: string; kind: string; url: string; license: string; rights_evidence: string; attribution: string; niche: string; enabled: boolean; last_polled_at: string | null };
export type Account = { id: number; platform: string; name: string; connected: boolean; publishing_allowed: boolean; max_posts_per_day: number; can_publish: boolean; blocked_reason: string };
export type Platform = { platform: string; available: boolean; reason: string };
export type JobRow = { id: number; kind: string; status: string; attempts: number; max_attempts: number; run_after: string; last_error: string; created_at: string };
export type Budget = { daily_limit_usd: number; monthly_limit_usd: number; per_item_limit_usd: number; max_videos_per_day: number; total_limit_usd: number; max_videos_ceiling: number };
export type Costs = {
  by_category: Record<string, number>;
  entries: { id: number; at: string; category: string; usd: number; status: string; description: string; item_id: number | null }[];
};
export type Audit = { at: string; action: string; detail: string; ip: string };

export type Evaluation = {
  expected_payout: number;
  risk_adjusted_revenue: number;
  production_cost: number;
  expected_profit: number;
  p_reach_min: number;
  p_approval: number;
  p_payment: number;
  fee_pct: number;
  clips_affordable: number | null;
  view_model: string;
  assumptions: string[];
  label: string;
};
export type CampaignRow = {
  id: number;
  provider: string;
  external_id: string;
  name: string;
  creator: string;
  url: string;
  payout_model: string;
  rate_per_1k: number | null;
  flat_reward: number | null;
  budget_total: number | null;
  budget_remaining: number | null;
  min_payout: number | null;
  max_payout_per_video: number | null;
  platform_fee_pct: number;
  ends_at: string | null;
  platforms: string[];
  countries: string[];
  requirements: string;
  footage_urls: string[];
  submission_method: string;
  status: string;
  status_reason: string;
  evaluation: Partial<Evaluation>;
  submissions: Record<string, number>;
};
export type SubmissionRow = { id: number; campaign: string; campaign_url: string; provider: string; status: string; post_url: string; qualified_views: number | null; note: string; submitted_at: string | null };
export type RevenueRow = { id: number; stream: string; source: string; amount: number; currency: string; status: string; evidence: string; occurred_at: string };
export type Split = Record<string, { confirmed: number; pending: number }>;
export type Finance = {
  overview: {
    confirmed_today: number;
    confirmed_month: number;
    confirmed_all_time: number;
    pending: number;
    costs_month: number;
    costs_all_time: number;
    net_month_confirmed: number;
    qualified_views_total: number;
    videos_published: number;
    videos_generated: number;
    progress_to_100k: number;
    next_milestone: number | null;
    first_dollar_reached: boolean;
  };
  breakdown: { by_stream: Split; by_platform: Split; by_account: Split; by_campaign: Split };
  milestones: {
    basis: string;
    effective_rpm: number;
    views_per_video: number;
    cost_per_video: number;
    label: string;
    rows: {
      monthly_revenue: number;
      qualified_views_per_month: number;
      videos_per_month: number;
      videos_per_day: number;
      campaign_budget_needed: number;
      variable_cost: number;
      operating_cost: number;
      est_profit: number;
      channels_needed: number;
    }[];
  };
  last_14d: { videos: number; paid_videos: number; confirmed: number; pending: number; cost: number };
};
