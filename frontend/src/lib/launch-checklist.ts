export type ScanStatus =
  | "pending"
  | "discovering"
  | "inventory"
  | "vitals"
  | "analyzing"
  | "completed"
  | "failed"
  | "canceled"

export const ACTIVE_STATUSES: ScanStatus[] = [
  "pending",
  "discovering",
  "inventory",
  "vitals",
  "analyzing",
]

export type CwvRating = "good" | "needs_improvement" | "poor"

export type SummaryStats = {
  total_urls: number
  status: Record<string, number>
  html_pages: number
  indexable: number
  non_indexable: number
  http2_pages: number
  missing_title: number
  missing_meta: number
  missing_h1: number
  multiple_h1: number
  broken_link_pages: number
  images_missing_alt: number
  avg_response_ms: number | null
  avg_word_count: number | null
  redirects: number
  final_4xx: number
  cwv: {
    measured: number
    good: number
    needs_improvement: number
    poor: number
    avg_performance_score: number | null
  }
  issues: {
    total: number
    by_severity: Record<string, number>
    by_category: Record<string, number>
    by_type: Record<string, number>
  }
}

export type LaunchScan = {
  id: string
  customer_website_id: string
  phase: number
  status: ScanStatus
  base_url: string
  discovery_source: string | null
  total_urls: number
  inventoried_urls: number
  failed_urls: number
  max_pages: number
  vitals_max_pages: number
  vitals_total: number
  vitals_measured: number
  summary_stats: SummaryStats | null
  warnings: string[] | null
  error_message: string | null
  created_by: string
  created_at: string
  updated_at: string
  completed_at: string | null
}

export type AiCheck = {
  key: string
  label: string
  status: "ok" | "warning" | "error"
  message: string
  details: unknown
}

export type AiChecks = {
  score: number
  checks: AiCheck[]
  bots: { bot: string; label: string; allowed: boolean }[]
}

export type AgentTrace = {
  model?: string
  steps?: { step: number; tool: string; arguments: Record<string, unknown>; output_preview: string }[]
  usage?: { input_tokens: number; output_tokens: number }
  stopped_reason?: string
  error?: string
}

export type LaunchScanDetail = LaunchScan & {
  ai_checks: AiChecks | null
  ai_summary: string | null
  agent_trace: AgentTrace | null
}

export type LaunchCustomer = {
  id: string
  name: string
  base_url: string
  domain: string
  category_name: string | null
  latest_scan: LaunchScan | null
}

export type CwvMetric = { value: number | null; rating: CwvRating | null }

export type CwvData = {
  lab?: {
    lcp: number | null
    cls: number | null
    tbt: number | null
    fcp: number | null
    si: number | null
    ttfb: number | null
    performance_score: number | null
  }
  field?: ({ origin_fallback: boolean; overall: CwvRating | null } & Partial<
    Record<"lcp" | "inp" | "cls" | "fcp" | "ttfb", CwvMetric>
  >) | null
  status?: CwvRating | null
  source?: "field" | "lab"
  error?: string
}

export type LaunchScanPage = {
  id: string
  url: string
  path: string
  in_sitemap: boolean
  status_code: number | null
  final_url: string | null
  redirect_chain: { url: string; status: number; location?: string; final?: boolean }[] | null
  response_time_ms: number | null
  content_type: string | null
  size_bytes: number | null
  http_version: string | null
  indexable: boolean | null
  indexability_reason: string | null
  meta_robots: string | null
  title: string | null
  title_length: number | null
  meta_description: string | null
  meta_description_length: number | null
  h1: string[] | null
  h1_count: number | null
  h2: string[] | null
  canonical: string | null
  word_count: number | null
  lang: string | null
  hreflang: { lang: string; href: string }[] | null
  internal_links: number | null
  external_links: number | null
  broken_links: { url: string; status: number | null }[] | null
  images_total: number | null
  images_missing_alt: number | null
  schema_types: string[] | null
  open_graph: Record<string, string> | null
  cwv: CwvData | null
  cwv_status: CwvRating | null
  error: string | null
  issue_count: number
}

export type IssueStatus = "open" | "doorgezet" | "opgelost" | "genegeerd"
export type IssueSeverity = "hoog" | "middel" | "laag"

export type LaunchScanIssue = {
  id: string
  scan_id: string
  page_id: string | null
  issue_type: string
  issue_label: string | null
  category: string
  severity: IssueSeverity
  title: string
  description: string
  recommendation: string | null
  url: string | null
  details: unknown
  status: IssueStatus
  external_provider: string | null
  external_item_id: string | null
  external_url: string | null
  pushed_at: string | null
  created_at: string
  updated_at: string
}

export type IssueGroup = {
  issue_type: string
  label: string
  category: string
  severity: IssueSeverity
  count: number
  open: number
}

export const API_BASE = "/api/launch-checklist"

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { cache: "no-store", ...init })
  const payload = (await response.json().catch(() => null)) as (T & { error?: string }) | null
  if (!response.ok) {
    throw new Error(payload?.error?.trim() || "Er ging iets mis.")
  }
  return payload as T
}

export const STATUS_LABELS: Record<ScanStatus, string> = {
  pending: "In de wachtrij",
  discovering: "Sitemap ophalen",
  inventory: "Site-inventaris",
  vitals: "Core Web Vitals meten",
  analyzing: "AI-analyse",
  completed: "Voltooid",
  failed: "Mislukt",
  canceled: "Geannuleerd",
}

export const SEVERITY_LABELS: Record<IssueSeverity, string> = {
  hoog: "Hoog",
  middel: "Middel",
  laag: "Laag",
}

export const CATEGORY_LABELS: Record<string, string> = {
  techniek: "Techniek",
  "on-page": "On-page",
  content: "Content",
  performance: "Performance",
  ai: "AI-vindbaarheid",
}

export const ISSUE_STATUS_LABELS: Record<IssueStatus, string> = {
  open: "Open",
  doorgezet: "Doorgezet",
  opgelost: "Opgelost",
  genegeerd: "Genegeerd",
}

export const CWV_LABELS: Record<CwvRating, string> = {
  good: "Goed",
  needs_improvement: "Verbeteren",
  poor: "Slecht",
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return "—"
  return new Intl.DateTimeFormat("nl-NL", { dateStyle: "medium", timeStyle: "short" }).format(date)
}
