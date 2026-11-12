export type ScanStatus =
  | "pending"
  | "discovering"
  | "inventory"
  | "vitals"
  | "analyzing"
  | "fetching"
  | "linking"
  | "checking"
  | "completed"
  | "failed"
  | "canceled"

export const ACTIVE_STATUSES: ScanStatus[] = [
  "pending",
  "discovering",
  "inventory",
  "vitals",
  "analyzing",
  "fetching",
  "linking",
  "checking",
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
  source_scan_id: string | null
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
  /** Fase 4: ronde (kwartaal), bijv. "2026-Q4". */
  period?: string | null
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
  /** Fase 3: opgetelde tokens van alle AI-analyses van deze scan. */
  analysis_usage?: { input_tokens: number; output_tokens: number; calls: number }
  model?: string
  steps?: { step: number; tool: string; arguments: Record<string, unknown>; output_preview: string }[]
  usage?: { input_tokens: number; output_tokens: number }
  stopped_reason?: string
  error?: string
}

/** Ahrefs-snapshot van het domein (alleen op een fase 1-scan). */
export type AhrefsScan = {
  target: string
  country: string
  fetched_at: string
  /** Scan waarvan de data is overgenomen (herscan binnen de bewaartermijn: 0 units). */
  reused_from: string | null
  units: number
  domain: {
    domain_rating?: number | null
    refdomains?: number | null
    backlinks?: number | null
    org_traffic?: number | null
    org_keywords?: number | null
    org_keywords_1_3?: number | null
    /** Geschatte waarde van het organische verkeer, in dollarcenten per maand. */
    org_cost?: number | null
  }
  errors: string[]
  pages_with_traffic: number
  pages_with_backlinks: number
  /** URL's die Ahrefs kent maar die niet in de crawl zaten. */
  extra_urls: number
  /** URL's met verkeer of backlinks die niet (meer) werken. */
  lost_value_urls: number
}

/** Ahrefs-details per pagina; verkeer en verwijzende domeinen staan los op de pagina. */
export type AhrefsPage = {
  /** "ahrefs" = de URL zat niet in de crawl en is alleen bij Ahrefs bekend. */
  source: "crawl" | "ahrefs"
  keywords?: number
  top_keyword?: string
  top_keyword_position?: number
  top_keyword_volume?: number
  dofollow_backlinks?: number
  broken_backlinks?: { url_from: string; dr: number | null; anchor: string }[]
}

/** Het zoekwoord waarop een pagina nu het meeste organische verkeer krijgt (Ahrefs). */
export type AhrefsKeyword = {
  keyword: string
  position: number | null
  volume: number | null
  traffic: number | null
}

/** Waarom een actiepunt zwaarder weegt: de pagina heeft verkeer of backlinks. */
export type ValueBoost = { org_traffic: number | null; refdomains: number | null; from: IssueSeverity | null }

export function valueBoostOf(details: unknown): ValueBoost | null {
  if (!details || typeof details !== "object") return null
  const boost = (details as { value_boost?: unknown }).value_boost
  return boost && typeof boost === "object" ? (boost as ValueBoost) : null
}

export function formatCount(value: number | null | undefined) {
  return value == null ? "—" : value.toLocaleString("nl-NL")
}

export type LaunchScanDetail = LaunchScan & {
  ai_checks: AiChecks | null
  ahrefs?: AhrefsScan | null
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
  latest_geo_scan: LaunchScan | null
  checklist_progress: ChecklistProgress | null
  latest_content_scan: LaunchScan | null
  content_progress: ChecklistProgress | null
  /** Fase 2/3 gebaseerd op een oudere nulmeting dan de nieuwste (ook lopende). */
  geo_outdated?: boolean
  content_outdated?: boolean
  /** Fase 4: laatste scan en de voortgang van de ronde van die scan. */
  latest_quarterly_scan?: LaunchScan | null
  quarterly_progress?: ChecklistProgress | null
  quarterly_period?: string | null
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
  page_type: string | null
  page_type_source: "rule" | "ai" | "manual" | null
  click_depth: number | null
  inlinks: number | null
  schema_all: string[] | null
  /** Ahrefs: geschat organisch verkeer per maand en aantal verwijzende domeinen. */
  org_traffic: number | null
  refdomains: number | null
  ahrefs: AhrefsPage | null
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
  fetching: "Pagina's ophalen",
  linking: "Paginatypes & linkgraaf",
  checking: "Checklist controleren",
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
  schema: "Schema.org",
  entiteit: "Entiteit & vertrouwen",
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

// --- fase 2: GEO/SEO-checklist ---------------------------------------------

export type ChecklistProgress = { done: number; total: number; percent: number }

export type AutoStatus = "ok" | "warning" | "error" | "nvt" | "unknown" | "info"
export type ManualStatus = "open" | "afgerond" | "nvt"
export type EffectiveStatus = "done" | "open" | "nvt"

export type ChecklistAuto = {
  status: AutoStatus
  message: string
  evidence: string[]
  details: unknown
}

export type ChecklistItem = {
  key: string
  label: string
  description: string | null
  mode: "auto" | "manual" | "hybrid"
  applies_to: "all" | "webshop"
  priority: "hoog" | "normaal" | "laag"
  auto: ChecklistAuto | null
  manual_status: ManualStatus | null
  note: string | null
  updated_at: string | null
  external_url: string | null
  pushed_at: string | null
  effective: EffectiveStatus
  f1_issue_types: string[]
}

export type ChecklistSection = {
  key: string
  label: string
  items: ChecklistItem[]
  done: number
  total: number
}

export type Checklist = ChecklistProgress & {
  customer_id: string
  customer_name: string
  base_url: string
  scan: LaunchScan | null
  source_scan_id: string | null
  is_webshop: boolean
  webshop_detected: boolean | null
  webshop_override: boolean | null
  webshop_reasons: string[]
  page_types: Record<string, number>
  generated_at: string | null
  sections: ChecklistSection[]
}

// --- Fase 3: content & onpage ------------------------------------------------

/** Welke checklist: fase 2 (GEO/SEO), fase 3 (content & onpage) of fase 4 (kwartaal). */
export type ChecklistPath = "checklist" | "content-checklist" | "quarterly-checklist"

export type ContentSummary = {
  pages_fetched: number
  pages_with_problems: number
  pages_analysed: number
  suggestions_open: number
}

export type ContentChecklist = ChecklistProgress & {
  customer_id: string
  customer_name: string
  base_url: string
  scan: LaunchScan | null
  source_scan_id: string | null
  page_types: Record<string, number>
  generated_at: string | null
  gap_analyzed_at: string | null
  summary: ContentSummary | null
  max_pages_per_analysis: number
  sections: ChecklistSection[]
}

export type AnalysisStatus = "none" | "queued" | "running" | "done" | "failed"
export type SuggestionStatus = "open" | "overgenomen" | "afgewezen"

export type ContentCheck = { status: AutoStatus; message: string; details?: unknown }

/** Eén <a>-tag naar een kapot of doorverwezen doel; `href` zoals hij in de HTML staat. */
export type LinkAnchor = { text: string; href: string; in_content: boolean }

/** Kapotte of doorverwezen interne link (`c3_redirects_404`). Oudere scans hebben geen `anchors`. */
export type LinkProblem = {
  url: string
  text: string
  status: number | null
  final_url?: string | null
  final_status?: number | null
  in_content?: boolean
  anchors?: LinkAnchor[]
}

export type RedirectDetails = {
  broken?: LinkProblem[]
  redirects?: LinkProblem[]
  broken_total?: number
  redirects_total?: number
}

export type ImageProblem = {
  src: string
  filename: string
  alt: string | null
  missing_alt: boolean
  generic_filename: boolean
}

export type InternalLinkDetails = { generic?: { url: string; text: string }[] }

export type ContentSuggestion = {
  id: string
  scan_id: string
  content_page_id: string | null
  page_url: string | null
  item_key: string
  item_label: string
  agent: string
  title: string | null
  current_value: string | null
  proposed_value: string
  rationale: string | null
  details: { ref?: string; length?: number; pixels?: number; trimmed_from?: string } | null
  status: SuggestionStatus
  created_at: string
  updated_at: string
}

export type ContentPage = {
  id: string
  url: string
  path: string
  page_type: string | null
  title: string | null
  meta_description: string | null
  word_count: number | null
  problem_count: number
  checks: Record<string, ContentCheck>
  analysis_status: AnalysisStatus
  analysis_error: string | null
  focus_keyword: string | null
  intent: string | null
  keyword_source: string | null
  ahrefs_keyword: AhrefsKeyword | null
  analyzed_at: string | null
  suggestions_open: number
  suggestions_total: number
  /** Checklistpunten waarvoor deze pagina open AI-voorstellen heeft. */
  suggestion_items: string[]
}

export type ContentPageDetail = ContentPage & {
  headings: { level: number; text: string }[] | null
  first_paragraph: string | null
  readability: string | null
  images_total: number
  links_total: number
  suggestions: ContentSuggestion[]
}

export const ANALYSIS_STATUS_LABELS: Record<AnalysisStatus, string> = {
  none: "Niet geanalyseerd",
  queued: "In wachtrij",
  running: "Bezig…",
  done: "Geanalyseerd",
  failed: "Mislukt",
}

export const SUGGESTION_STATUS_LABELS: Record<SuggestionStatus, string> = {
  open: "Open",
  overgenomen: "Overgenomen",
  afgewezen: "Afgewezen",
}

export const AGENT_LABELS: Record<string, string> = {
  content_meta: "Meta",
  content_text: "Tekst & structuur",
  content_trust: "Vertrouwen & conversie",
  content_links: "Links & afbeeldingen",
  content_gap: "Contentgap",
}

export const INTENTS = ["informatief", "commercieel", "transactioneel", "navigatie", "lokaal"] as const

export const KEYWORD_SOURCE_LABELS: Record<string, string> = {
  ai: "AI",
  manual: "Handmatig",
  ahrefs: "Ahrefs",
}

/** Focuszoekwoord handmatig vastleggen; leeg = weer automatisch (Ahrefs-ranking, anders de AI). */
export function updatePageKeyword(scanId: string, pageId: string, focus_keyword: string, intent: string | null) {
  return apiFetch<ContentPageDetail>(`/scans/${scanId}/content-pages/${pageId}/keyword`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ focus_keyword, intent }),
  })
}

export function updateSuggestionStatus(id: string, status: SuggestionStatus) {
  return apiFetch<ContentSuggestion>(`/suggestions/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  })
}

export const PAGE_TYPE_LABELS: Record<string, string> = {
  home: "Homepage",
  dienst: "Dienstpagina",
  product: "Productpagina",
  categorie: "Categoriepagina",
  blog: "Blog / artikel",
  vacature: "Vacature",
  over_ons: "Over ons / team",
  contact: "Contact",
  overzicht: "Overzichtspagina",
  archief: "Archief",
  juridisch: "Juridisch",
  overig: "Overig",
}

/** Verwachte schema-types per paginatype (zelfde logica als de backend-checks). */
export const EXPECTED_SCHEMA: Record<string, string[]> = {
  home: ["Organization", "WebSite"],
  dienst: ["Service", "BreadcrumbList"],
  product: ["Product", "Brand", "BreadcrumbList"],
  categorie: ["ItemList", "BreadcrumbList"],
  blog: ["BlogPosting|Article", "Person", "BreadcrumbList"],
  vacature: ["JobPosting", "BreadcrumbList"],
  over_ons: ["Person", "BreadcrumbList"],
  contact: ["BreadcrumbList"],
}

export const AUTO_STATUS_LABELS: Record<AutoStatus, string> = {
  ok: "In orde",
  warning: "Aandacht",
  error: "Probleem",
  nvt: "N.v.t.",
  unknown: "Onbekend",
  info: "Handmatig",
}

export const MANUAL_STATUS_LABELS: Record<ManualStatus, string> = {
  open: "Open",
  afgerond: "Afgerond",
  nvt: "N.v.t.",
}

export const MODE_LABELS: Record<ChecklistItem["mode"], string> = {
  auto: "Automatisch",
  manual: "Handmatig",
  hybrid: "Hint + handmatig",
}

// --- Monday ---------------------------------------------------------------

export type MondaySettings = {
  token_configured: boolean
  folder_name: string
  board_id: string | null
  board_url: string | null
  board_name: string | null
  board_error: string | null
}

type MondayPushResponse = {
  board_url: string | null
  pushed: number
  skipped: number
  failed: number
  outcomes: { ref: string; status: "pushed" | "skipped" | "failed"; message: string | null; external_url: string | null }[]
}

export type MondayPushSummary = {
  pushed: number
  skipped: number
  failed: number
  /** Unieke meldingen van mislukte punten en waarschuwingen. */
  messages: string[]
  board_url: string | null
}

export type MondayPushTarget =
  | { kind: "issues" }
  | { kind: "checklist"; customerId: string; path?: ChecklistPath; period?: string }

/** De backend accepteert maximaal dit aantal punten per request. */
const MONDAY_BATCH_SIZE = 25
/** Afgevuurd na elke wijziging aan de Monday-koppeling (bord aangemaakt, punten doorgezet). */
export const MONDAY_CHANGED_EVENT = "livegang:monday-changed"

function notifyMondayChanged() {
  if (typeof window !== "undefined") window.dispatchEvent(new Event(MONDAY_CHANGED_EVENT))
}

const JSON_HEADERS = { "Content-Type": "application/json" }

export function fetchMondaySettings(customerId: string) {
  return apiFetch<MondaySettings>(`/customers/${customerId}/monday`)
}

export async function createMondayBoard(customerId: string) {
  const result = await apiFetch<MondaySettings>(`/customers/${customerId}/monday/board`, { method: "POST", headers: JSON_HEADERS, body: "{}" })
  notifyMondayChanged()
  return result
}

/** Koppel een bestaand bord (id of URL); `null` ontkoppelt. */
export async function linkMondayBoard(customerId: string, board: string | null) {
  const result = await apiFetch<MondaySettings>(`/customers/${customerId}/monday`, {
    method: "PATCH",
    headers: JSON_HEADERS,
    body: JSON.stringify({ board }),
  })
  notifyMondayChanged()
  return result
}

// --- Search Console ---------------------------------------------------------

export type SearchConsoleSettings = {
  /** Of de GSC_*-instellingen in de backend zijn gezet. */
  configured: boolean
  /** De property die de fase 4-scan gebruikt. */
  property: string | null
  property_source: "manual" | "auto" | null
  /** Properties die bij het domein passen, beste eerst. */
  candidates: string[]
  /** Alle properties waar het Google-account bij kan. */
  properties: { site_url: string; permission: string }[]
  error: string | null
}

export function fetchSearchConsoleSettings(customerId: string, refresh = false) {
  return apiFetch<SearchConsoleSettings>(`/customers/${customerId}/search-console${refresh ? "?refresh=true" : ""}`)
}

/** Kies de property van de klant; null = weer automatisch op domein. */
export function setSearchConsoleProperty(customerId: string, property: string | null) {
  return apiFetch<SearchConsoleSettings>(`/customers/${customerId}/search-console`, {
    method: "PATCH",
    headers: JSON_HEADERS,
    body: JSON.stringify({ property }),
  })
}

/**
 * Ruimt koppelingen op naar items die in Monday verwijderd zijn, zodat die
 * punten weer als niet-doorgezet verschijnen. Geeft het aantal opgeruimde
 * koppelingen terug; een fout hier mag de pagina niet blokkeren.
 */
export async function syncMondayLinks(customerId: string): Promise<number> {
  try {
    const result = await apiFetch<{ cleared: number }>(`/customers/${customerId}/monday/sync`, {
      method: "POST",
      headers: JSON_HEADERS,
      body: "{}",
    })
    return result.cleared
  } catch {
    return 0
  }
}

/**
 * Zet punten in batches door naar Monday. Stopt bij de eerste batch die als
 * geheel mislukt; wat al doorgezet is blijft staan en staat in de samenvatting.
 */
export async function pushToMonday(
  target: MondayPushTarget,
  refs: string[],
  onProgress?: (done: number, total: number) => void
): Promise<MondayPushSummary> {
  const summary: MondayPushSummary = { pushed: 0, skipped: 0, failed: 0, messages: [], board_url: null }
  const messages = new Set<string>()
  const path =
    target.kind === "issues"
      ? "/issues/push-monday"
      : `/customers/${target.customerId}/${target.path ?? "checklist"}/push-monday${periodQuery(target.period)}`
  const bodyKey = target.kind === "issues" ? "issue_ids" : "item_keys"
  try {
    for (let start = 0; start < refs.length; start += MONDAY_BATCH_SIZE) {
      const batch = refs.slice(start, start + MONDAY_BATCH_SIZE)
      onProgress?.(start, refs.length)
      let response: MondayPushResponse
      try {
        response = await apiFetch<MondayPushResponse>(path, {
          method: "POST",
          headers: JSON_HEADERS,
          body: JSON.stringify({ [bodyKey]: batch }),
        })
      } catch (err) {
        summary.failed += refs.length - start
        messages.add((err as Error).message)
        break
      }
      summary.pushed += response.pushed
      summary.skipped += response.skipped
      summary.failed += response.failed
      summary.board_url = response.board_url ?? summary.board_url
      for (const outcome of response.outcomes) {
        if (outcome.message && (outcome.status === "failed" || outcome.status === "pushed")) messages.add(outcome.message)
      }
    }
  } finally {
    summary.messages = [...messages]
    notifyMondayChanged()
  }
  return summary
}

export function describeMondayPush(summary: MondayPushSummary): string {
  const parts = [`${summary.pushed} doorgezet`]
  if (summary.skipped) parts.push(`${summary.skipped} al doorgezet`)
  if (summary.failed) parts.push(`${summary.failed} mislukt`)
  return `Monday: ${parts.join(" · ")}.`
}

// --- Fase 4: kwartaal GEO-werkzaamheden ----------------------------------------

/** Query-deel voor een ronde (leeg = huidige ronde, die kiest de backend). */
export function periodQuery(period: string | null | undefined): string {
  return period ? `?period=${encodeURIComponent(period)}` : ""
}

export type QuarterlyPeriodOption = { period: string; label: string; scanned: boolean }

export type AiCheckChange = {
  key: string
  label: string
  before: AiCheck["status"] | null
  after: AiCheck["status"]
  message: string | null
  change: "better" | "worse" | "same" | "new"
}

export type IssueChange = {
  issue_type: string
  label: string
  category: string
  before: number
  after: number
  delta: number
}

export type AhrefsMetricChange = {
  key: string
  label: string
  before: number | null
  after: number | null
  delta: number | null
}

export type RankingRow = {
  keyword: string
  before: number | null
  after: number | null
  /** Positief = gestegen. */
  delta: number | null
  url: string | null
  checked_at: string | null
}

export type QuarterlyComparison = {
  base: { scan_id: string; phase: number; period: string | null; label: string; completed_at: string | null } | null
  ai: { before: number | null; after: number | null; checks: AiCheckChange[]; improved: number; worsened: number }
  issues: { before: number; after: number; rows: IssueChange[] }
  pages: { before: number; after: number; new: number; removed: number; broken: number; new_examples: string[] }
  ahrefs: {
    metrics: AhrefsMetricChange[]
    fetched_before: string | null
    fetched_after: string | null
    /** Zelfde Ahrefs-meting als de basis (hergebruikt binnen de bewaartermijn). */
    same_snapshot?: boolean
    lost_value_urls: number | null
  } | null
  rankings: {
    keywords: number
    top3: number
    top10: number
    improved: number
    declined: number
    compared: number
    last_checked_at: string | null
    rows: RankingRow[]
  } | null
  /** Search Console: meetperiode t.o.v. de periode ervoor. null = niet gekoppeld of geen data. */
  search_console?: QuarterlySearchConsole | null
}

export type GscSpan = { start: string; end: string; days: number }

export type GscMetricChange = {
  key: "clicks" | "impressions" | "ctr" | "position"
  label: string
  /** Periode ervoor. */
  before: number | null
  /** Meetperiode. */
  after: number | null
  delta: number | null
  pct: number | null
  last_year: number | null
  pct_last_year: number | null
}

/** Zoekopdracht of pagina; `key` is de zoekopdracht of de URL. Vorige waarden zijn null als ze onbekend zijn. */
export type GscRow = {
  key: string
  clicks: number | null
  impressions: number | null
  ctr: number | null
  position: number | null
  clicks_prev: number | null
  impressions_prev: number | null
  position_prev: number | null
  delta?: number
}

export type GscMovers = { total: number; top: GscRow[]; risers: GscRow[]; fallers: GscRow[] }

export type GscSitemap = {
  path: string
  last_submitted: string | null
  last_downloaded: string | null
  is_pending: boolean
  is_index: boolean
  errors: number
  warnings: number
  submitted: number
}

export type GscNotIndexed = {
  url: string
  /** "blocked": door iets op de site; "not_indexed": (nog) niet opgenomen zonder harde oorzaak. */
  state: "blocked" | "not_indexed"
  reason: string | null
  last_crawl_time: string | null
  google_canonical: string | null
  link: string | null
}

export type QuarterlySearchConsole = {
  property: string
  property_source: "manual" | "auto" | null
  period: GscSpan
  previous: GscSpan
  last_year: GscSpan
  has_performance: boolean
  metrics: GscMetricChange[]
  queries: GscMovers
  pages: GscMovers
  sitemaps: { total: number; with_errors: number; with_warnings: number; rows: GscSitemap[] } | null
  inspection: { requested: number; checked: number; indexed: number; not_indexed: GscNotIndexed[] } | null
  fetched_at: string | null
}

export type QuarterlySources = {
  ahrefs: boolean
  seo_tracker: boolean
  search_console: boolean | null
  ga4: boolean | null
  bing_webmaster: boolean | null
}

export type QuarterlyChecklist = ChecklistProgress & {
  customer_id: string
  customer_name: string
  base_url: string
  period: string
  period_label: string
  current_period: string
  periods: QuarterlyPeriodOption[]
  scan: LaunchScan | null
  generated_at: string | null
  comparison: QuarterlyComparison | null
  sources: QuarterlySources | null
  summary: { auto_status: Record<string, number>; pages: number; new_pages: number; broken_pages: number } | null
  sections: ChecklistSection[]
}

/** Nieuwe pagina (`c4_new_pages`). */
export type NewPageRow = {
  page_id: string
  url: string
  path: string
  status_code: number | null
  indexable: boolean | null
  in_sitemap: boolean
  result: "ok" | "warning" | "error"
  problems: string[]
  /** Indexstatus volgens de URL-inspectie van Search Console; null = niet geïnspecteerd. */
  google?: { state: "indexed" | "blocked" | "not_indexed"; reason: string | null } | null
}

export type NewPagesDetails = {
  new_total: number
  new: NewPageRow[]
  broken_total: number
  broken: { page_id: string; url: string; path: string; before: number | null; status_code: number | null }[]
  removed_total: number
  removed: string[]
}

export type SchemaProblem = { type: string; severity: "error" | "warning"; missing: string[]; problems: string[] }

/** Schema-validatie (`c4_schema_validation`). */
export type SchemaValidationDetails = {
  checked: number
  with_schema: number
  error_pages: number
  warning_pages: number
  pages: {
    page_id: string
    url: string
    path: string
    result: "error" | "warning"
    invalid_blocks: number
    problems: SchemaProblem[]
    lost_types: string[]
  }[]
}

export function periodLabel(period: string | null | undefined): string {
  const match = /^(\d{4})-Q([1-4])$/.exec(period ?? "")
  return match ? `Q${match[2]} ${match[1]}` : period ?? ""
}
