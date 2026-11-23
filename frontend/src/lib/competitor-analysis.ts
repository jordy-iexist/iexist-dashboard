/**
 * Concurrentieanalyse per klant: types, API-aanroepen, labels en de schatting.
 * Alles loopt via de proxy onder `/api/competitor-analyses`.
 *
 * De types volgen `backend/app/features/competitor_analysis/schemas.py` één-op-één
 * (zelfde veldnamen). Eenheden zoals daar: `lcp_ms` in milliseconden, duur in seconden,
 * Ahrefs in units, werkelijk Claude-verbruik in USD (`AiUsage.cost_usd`) en de schatting
 * in euro (`Estimate.ai_cost_eur`). Posities zijn 1-gebaseerd; tijdstippen zijn ISO-tekst.
 */

import { customerHref } from "@/lib/active-customer"

// --- Statussen en constanten ----------------------------------------------------------------

export type AnalysisStatus =
  | "pending"
  | "serp"
  | "fetching"
  | "analyzing"
  | "completed"
  | "failed"
  | "canceled"

export const ACTIVE_STATUSES: readonly AnalysisStatus[] = ["pending", "serp", "fetching", "analyzing"]
export const FINAL_STATUSES: readonly AnalysisStatus[] = ["completed", "failed", "canceled"]

/** Per zoekwoord: `failed` als alleen dit zoekwoord mislukte; de rest loopt door. */
export type KeywordStatus = "pending" | "completed" | "failed"

/** De zes vinkjes onder "Wat analyseren?" in de wizard. */
export type Module = "serp" | "onpage" | "topics" | "authority" | "tech" | "eeat"
export const ALL_MODULES: readonly Module[] = ["serp", "onpage", "topics", "authority", "tech", "eeat"]

/** Toestand van een databron (ook van de Google-poging per zoekwoord). */
export type SourceState = "ok" | "not_configured" | "error" | "blocked" | "skipped" | "empty"
export type SourceKey = "ahrefs" | "prt" | "pagespeed" | "claude" | "google"
export const SOURCE_KEYS: readonly SourceKey[] = ["ahrefs", "prt", "pagespeed", "claude", "google"]

/** Toestand van de AI-stap per zoekwoord. */
export type AiState = "ok" | "not_configured" | "error" | "skipped"

/** Uitkomst van het ophalen van één pagina; `null` = nog niet opgehaald. */
export type FetchStatus = "ok" | "blocked" | "not_html" | "error"

export type PageType = "dienst" | "product" | "categorie" | "blog" | "vergelijker" | "homepage" | "overig"

/** Waarom een pagina niet meetelt in de medianen. */
export type ExcludeReason = "aggregator" | "own_site"

export type Level = "hoog" | "middel" | "laag"

/** Herkomst van de eigen positie. */
export type PositionSource = "prt" | "ahrefs"

export type TopN = 3 | 5 | 10 | 20
export const TOP_N_OPTIONS: readonly TopN[] = [3, 5, 10, 20]

export type CwvSource = "lab" | "field"
export type MissingTopicKind = "topic" | "question"

/** Metrieken in de vergelijkingstabel waarop de eigen pagina een rode vlag kan krijgen. */
export type FlagMetric = "words" | "h2_count" | "faq" | "schema" | "refdomains" | "domain_rating" | "lcp_ms"
export const FLAG_METRICS: readonly FlagMetric[] = [
  "words",
  "h2_count",
  "faq",
  "schema",
  "refdomains",
  "domain_rating",
  "lcp_ms",
]

/**
 * Maximum aantal zoekwoorden per analyse. Het voorstel (`ProposalResponse.max_keywords`) is
 * leidend; dit getal is voor plekken zonder voorstel, zoals de Quick wins-selectie.
 */
export const MAX_KEYWORDS = 10

// --- Vorm van de JSON-kolommen die in de antwoorden zitten ----------------------------------

/** E-E-A-T-signalen op een pagina volgens de AI. */
export type Eeat = {
  team: boolean
  cases: boolean
  reviews: boolean
  certifications: boolean
  note: string | null
}

/** "Mensen vragen ook" uit de Google-poging. */
export type Paa = {
  state: SourceState
  questions: string[]
}

export type AiOverviewSource = {
  domain: string
  url: string | null
}

/** AI Overview-bronnen; `own_cited` null = onbekend. */
export type AiOverview = {
  state: SourceState
  sources: AiOverviewSource[]
  own_cited: boolean | null
}

/**
 * Onderwerp dat de eigen pagina mist. `covered` = aantal meegetelde concurrenten dat het
 * behandelt, `total` = aantal meegetelde concurrenten.
 */
export type MissingTopic = {
  topic: string
  kind: MissingTopicKind
  covered: number
  total: number
}

export type SourceStatus = {
  state: SourceState
  message: string | null
}

export type Sources = Record<SourceKey, SourceStatus>

/** Schatting vooraf. */
export type Estimate = {
  pages: number
  seconds: number
  ahrefs_units: number
  ai_cost_eur: number
}

/** Werkelijk Claude-verbruik van een run (kosten in USD). */
export type AiUsage = {
  calls: number
  input_tokens: number
  output_tokens: number
  cost_usd: number
}

// --- Voorstel voor de wizard ----------------------------------------------------------------

export type ProposalKeyword = {
  keyword: string
  url: string | null
  position: number | null
  volume: number | null
  source: PositionSource
}

export type ProposalDefaults = {
  country: string
  top_n: TopN
  exclude_aggregators: boolean
  modules: Module[]
}

/** Tarieven voor de schatting (uit `services/estimate.py` van de backend). */
export type Rates = {
  /** Units per opgevraagde SERP-positie; er worden `top_n + serp_extra_positions` posities opgevraagd. */
  ahrefs_units_per_serp_position: number
  serp_extra_positions: number
  /** Units per zoekwoord (volume/KD/intentie) en per URL (DR/RD van de eigen doelpagina). */
  ahrefs_units_per_keyword: number
  ahrefs_units_per_url: number
  /** Minimum per Ahrefs-aanvraag; zoekwoordgegevens en URL-metrics gaan elk in één aanvraag. */
  ahrefs_min_units_per_request: number
  claude_usd_per_page: number
  claude_eur_per_page: number
  claude_usd_per_keyword: number
  claude_eur_per_keyword: number
  seconds_per_page: number
  seconds_per_keyword: number
}

/** `GET /customers/{cid}/proposal`. */
export type ProposalResponse = {
  sources: Sources
  keywords: ProposalKeyword[]
  /** Unieke rankende URL's van de klant voor de keuzelijst "doelpagina". */
  pages: string[]
  defaults: ProposalDefaults
  rates: Rates
  max_keywords: number
}

// --- Starten --------------------------------------------------------------------------------

/** `target_url` null (of leeg) = er komt een nieuwe pagina. */
export type KeywordInput = {
  keyword: string
  target_url: string | null
}

/** `POST /customers/{cid}/analyses`. */
export type AnalysisCreateRequest = {
  keywords: KeywordInput[]
  /** ISO 3166-1 alpha-2 in kleine letters, bijv. "nl". */
  country: string
  top_n: TopN
  exclude_aggregators: boolean
  modules: Module[]
}

// --- Lijst ----------------------------------------------------------------------------------

export type AnalysisListItem = {
  id: string
  status: AnalysisStatus
  created_at: string
  completed_at: string | null
  top_n: number
  /** In de volgorde van de wizard. */
  keywords: string[]
  total_keywords: number
}

/** `GET /customers/{cid}/analyses`: nieuwste eerst. */
export type AnalysisListResponse = {
  items: AnalysisListItem[]
}

// --- Detail van een run ---------------------------------------------------------------------

/** Zoekwoord in de zoekwoordkiezer bovenaan het resultaat. */
export type KeywordSummary = {
  id: string
  keyword: string
  target_url: string | null
  status: KeywordStatus
  error_message: string | null
  own_position: number | null
  volume: number | null
  kd: number | null
  ai_state: AiState | null
  /** Status van de content brief (zie `lib/content-brief.ts`); null = nog geen brief. */
  brief_status: string | null
}

/** `GET /analyses/{id}`; ook het antwoord op starten en annuleren. */
export type AnalysisDetail = {
  id: string
  customer_website_id: string
  status: AnalysisStatus
  error_message: string | null
  warnings: string[]
  // Instellingen
  country: string
  top_n: number
  exclude_aggregators: boolean
  modules: Module[]
  // Voortgang
  total_keywords: number
  done_keywords: number
  total_pages: number
  fetched_pages: number
  failed_pages: number
  vitals_total: number
  vitals_measured: number
  // Bronnen, schatting en werkelijk verbruik
  sources: Sources
  estimate: Estimate | null
  ahrefs_units: number
  ai_usage: AiUsage | null
  created_by: string
  created_at: string
  updated_at: string
  completed_at: string | null
  keywords: KeywordSummary[]
}

// --- Resultaat per zoekwoord ----------------------------------------------------------------

/** Eén rij in de tabel "Jij vs. de top X". */
export type PageRow = {
  id: string
  position: number | null
  url: string
  domain: string | null
  serp_title: string | null
  page_type: PageType | null
  is_excluded: boolean
  exclude_reason: ExcludeReason | null
  fetch_status: FetchStatus | null
  fetch_error: string | null
  /** null als de pagina niet is uitgelezen. */
  words: number | null
  h2_count: number | null
  has_faq: boolean | null
  schema_types: string[]
  refdomains: number | null
  domain_rating: number | null
  lcp_ms: number | null
  /** Waarom er geen LCP is, bijv. "niet op tijd gemeten". */
  lcp_error: string | null
  eeat: Eeat | null
  /** Minder dan 50 woorden: "mogelijk niet leesbaar", telt niet mee in de medianen. */
  unreadable: boolean
}

/** De eigen doelpagina; `flags[metric]` true = duidelijk onder de mediaan (rood). */
export type OwnPageRow = PageRow & {
  flags: Partial<Record<FlagMetric, boolean>>
}

/** Mediaanrij over de meegetelde concurrenten; null = te weinig waarden ("—"). */
export type MedianRow = {
  words: number | null
  h2_count: number | null
  refdomains: number | null
  domain_rating: number | null
  lcp_ms: number | null
  faq_count: number
  schema_count: number
  schema_top: string | null
  /** Aantal meegetelde concurrenten (niet uitgesloten, opgehaald en leesbaar). */
  total: number
}

/** Verbeterpunt; ook het antwoord op `PATCH /actions/{action_id}`. */
export type ActionItem = {
  id: string
  title: string
  description: string | null
  impact: Level | null
  effort: Level | null
  category: Module | null
  done: boolean
  done_by_name: string | null
  done_at: string | null
}

/** `GET /analyses/{id}/keywords/{kid}`. */
export type KeywordDetail = {
  id: string
  analysis_id: string
  keyword: string
  target_url: string | null
  status: KeywordStatus
  error_message: string | null
  own_position: number | null
  own_position_source: PositionSource | null
  volume: number | null
  kd: number | null
  /** Actieve Ahrefs-intenties (bijv. "commercial") en SERP-featuretypes. */
  intents: string[]
  serp_features: string[]
  serp_date: string | null
  serp_summary: string | null
  search_intent: string | null
  ai_state: AiState | null
  ai_error: string | null
  /** Concurrenten in SERP-volgorde, zonder de eigen pagina. */
  pages: PageRow[]
  /** null als er geen doelpagina is (nieuwe pagina). */
  own: OwnPageRow | null
  median: MedianRow
  actions: ActionItem[]
  missing_topics: MissingTopic[]
  paa: Paa | null
  ai_overview: AiOverview | null
}

/** `PATCH /actions/{action_id}`. */
export type ActionUpdate = {
  done: boolean
}

// --- Labels ---------------------------------------------------------------------------------

export const ANALYSIS_STATUS_LABELS: Record<AnalysisStatus, string> = {
  pending: "In de wachtrij",
  serp: "Zoekresultaten ophalen",
  fetching: "Pagina's ophalen",
  analyzing: "Analyseren",
  completed: "Voltooid",
  failed: "Mislukt",
  canceled: "Geannuleerd",
}

/** De stappen van een lopende analyse, in volgorde (voor een voortgangsblok). */
export const ANALYSIS_STEPS: readonly AnalysisStatus[] = ["serp", "fetching", "analyzing"]

export const KEYWORD_STATUS_LABELS: Record<KeywordStatus, string> = {
  pending: "Bezig",
  completed: "Klaar",
  failed: "Mislukt",
}

/** Titel en omschrijving van de zes modules, zoals in het design. */
export const MODULES: Record<Module, { label: string; description: string }> = {
  serp: {
    label: "Zoekintentie & SERP-features",
    description: "Type pagina's in de top, local pack, AI Overview, Mensen vragen ook",
  },
  onpage: {
    label: "On-page & structuur",
    description: "Title, meta, H1–H3, woordaantal, interne links, afbeeldingen",
  },
  topics: {
    label: "Onderwerpdekking (AI)",
    description: "Welke subonderwerpen en vragen behandelen concurrenten wel en jij niet",
  },
  authority: {
    label: "Autoriteit & backlinks",
    description: "Verwijzende domeinen en DR (Ahrefs)",
  },
  tech: {
    label: "Techniek",
    description: "Core Web Vitals (PageSpeed) en schema.org",
  },
  eeat: {
    label: "E-E-A-T-signalen",
    description: "Team, cases, reviews, certificeringen",
  },
}

export const SOURCE_LABELS: Record<SourceKey, string> = {
  ahrefs: "Ahrefs",
  prt: "Pro Rank Tracker",
  pagespeed: "PageSpeed Insights",
  claude: "Claude (AI)",
  google: "Google",
}

export const SOURCE_STATE_LABELS: Record<SourceState, string> = {
  ok: "Beschikbaar",
  not_configured: "Niet ingesteld",
  error: "Fout",
  blocked: "Geblokkeerd",
  skipped: "Overgeslagen",
  empty: "Geen gegevens",
}

export const AI_STATE_LABELS: Record<AiState, string> = {
  ok: "Geanalyseerd",
  not_configured: "Niet ingesteld",
  error: "Mislukt",
  skipped: "Overgeslagen",
}

export const FETCH_STATUS_LABELS: Record<FetchStatus, string> = {
  ok: "Opgehaald",
  blocked: "Geblokkeerd",
  not_html: "Geen HTML-pagina",
  error: "Niet opgehaald",
}

export const PAGE_TYPE_LABELS: Record<PageType, string> = {
  dienst: "Dienstpagina",
  product: "Productpagina",
  categorie: "Categoriepagina",
  blog: "Blog",
  vergelijker: "Vergelijker",
  homepage: "Homepage",
  overig: "Overig",
}

export const EXCLUDE_REASON_LABELS: Record<ExcludeReason, string> = {
  aggregator: "Vergelijkingssite of gids",
  own_site: "Eigen site",
}

/** Voor impact en moeite van een verbeterpunt. */
export const LEVEL_LABELS: Record<Level, string> = {
  hoog: "Hoog",
  middel: "Middel",
  laag: "Laag",
}

export const POSITION_SOURCE_LABELS: Record<PositionSource, string> = {
  prt: "Pro Rank Tracker",
  ahrefs: "Ahrefs",
}

export const FLAG_METRIC_LABELS: Record<FlagMetric, string> = {
  words: "Woorden",
  h2_count: "H2's",
  faq: "FAQ",
  schema: "Schema",
  refdomains: "Ref. domeinen",
  domain_rating: "DR",
  lcp_ms: "LCP",
}

export const MISSING_TOPIC_KIND_LABELS: Record<MissingTopicKind, string> = {
  topic: "Onderwerp",
  question: "Vraag",
}

/** Landen die Ahrefs kent; een onbekende code toont `countryLabel` als hoofdletters. */
export const COUNTRY_LABELS: Record<string, string> = {
  nl: "Nederland",
  be: "België",
  de: "Duitsland",
  fr: "Frankrijk",
  gb: "Verenigd Koninkrijk",
  us: "Verenigde Staten",
}

export function countryLabel(code: string) {
  return COUNTRY_LABELS[code.toLowerCase()] ?? code.toUpperCase()
}

/**
 * Toestand van een kaart in het resultaat: gevuld, leeg, "niet ingesteld" of "niet beschikbaar".
 * `hasData` zegt of er iets te tonen is; de toestand van de bron gaat voor bij een lege kaart.
 */
export type CardState = "filled" | "empty" | "not_configured" | "unavailable"

export const CARD_STATE_LABELS: Record<Exclude<CardState, "filled">, string> = {
  empty: "Geen gegevens",
  not_configured: "Niet ingesteld",
  unavailable: "Niet beschikbaar",
}

export function cardState(state: SourceState | AiState | null | undefined, hasData: boolean): CardState {
  if (hasData) return "filled"
  if (state === "not_configured") return "not_configured"
  if (state === "error" || state === "blocked" || state === "skipped") return "unavailable"
  return "empty"
}

// --- Hulpfuncties ---------------------------------------------------------------------------

export function isActive(status: AnalysisStatus) {
  return ACTIVE_STATUSES.includes(status)
}

/** Naam van de queryparameter voor zoekwoorden (wizard) en het gekozen zoekwoord (resultaat). */
export const KEYWORD_PARAM = "zoekwoord"

/** Lijst van analyses van een klant. */
export function analysesHref(customerId: string) {
  return customerHref("analyses", customerId)
}

/** De wizard, eventueel met zoekwoorden al ingevuld (`?zoekwoord=a&zoekwoord=b`). */
export function newAnalysisHref(customerId: string, keywords?: string[]) {
  const params = new URLSearchParams()
  for (const keyword of keywords ?? []) params.append(KEYWORD_PARAM, keyword)
  const query = params.toString()
  return `${analysesHref(customerId)}/nieuw${query ? `?${query}` : ""}`
}

/** Resultaat van een analyse, eventueel direct op één zoekwoord (`?zoekwoord=<keywordId>`). */
export function analysisHref(customerId: string, analysisId: string, keywordId?: string | null) {
  const base = `${analysesHref(customerId)}/${encodeURIComponent(analysisId)}`
  return keywordId ? `${base}?${new URLSearchParams({ [KEYWORD_PARAM]: keywordId })}` : base
}

/** Zoekwoorden uit een (herhaalde) queryparameter: getrimd, zonder lege en dubbele. */
export function keywordsFromParam(value: string | string[] | undefined): string[] {
  const values = Array.isArray(value) ? value : value ? [value] : []
  const seen = new Set<string>()
  const result: string[] = []
  for (const raw of values) {
    const keyword = raw.split(/\s+/).filter(Boolean).join(" ")
    const key = keyword.toLowerCase()
    if (!keyword || seen.has(key)) continue
    seen.add(key)
    result.push(keyword)
  }
  return result
}

const dateTimeFormat = new Intl.DateTimeFormat("nl-NL", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "Europe/Amsterdam",
})

/** Datum en tijd van een analyse ("23 nov 2026, 14:05"); null bij een lege of ongeldige waarde. */
export function formatAnalysisDate(value: string | null | undefined) {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : dateTimeFormat.format(date)
}

/** "a, b, c +2": de eerste `max` zoekwoorden en het aantal dat er nog bij komt. */
export function formatKeywords(keywords: string[], total = keywords.length, max = 3) {
  const shown = keywords.slice(0, max).join(", ")
  const rest = Math.max(total, keywords.length) - Math.min(keywords.length, max)
  return rest > 0 ? `${shown} +${rest}` : shown
}

// --- Schatting ------------------------------------------------------------------------------

export type EstimateInput = {
  /** Aantal zoekwoorden. */
  keywords: number
  topN: number
  /** Aantal zoekwoorden met een eigen doelpagina (voor DR/RD van die URL's). */
  ownUrls: number
  modules: readonly Module[]
  /** Of er een Claude-sleutel is (`proposal.sources.claude.state === "ok"`). */
  aiConfigured: boolean
}

/**
 * Schatting voor de wizard. De backend rekent hetzelfde uit bij het starten en bewaart dat in
 * `AnalysisDetail.estimate`; dat getal is leidend.
 *
 * - pagina's = zoekwoorden × (top N + 1 eigen pagina)
 * - Ahrefs-units = SERP: zoekwoorden × (top N + extra SERP-posities) × units per positie
 *                + overzicht: zoekwoorden × units per zoekwoord
 *                + autoriteit (alleen met module "authority"): eigen URL's × units per URL
 * - Claude (EUR) = 0 zonder sleutel; anders de pagina-indeling (pagina's × tarief per pagina)
 *                + de inhoudsanalyse per zoekwoord (zoekwoorden × tarief per zoekwoord), die
 *                  alleen meetelt met module "topics" of "eeat"
 * - duur (s) = pagina's × seconden per pagina + zoekwoorden × seconden per zoekwoord
 */
export function estimate(rates: Rates, input: EstimateInput): Estimate {
  const { keywords, topN, ownUrls, modules, aiConfigured } = input
  const pages = keywords * (topN + 1)

  const serpUnits = keywords * (topN + rates.serp_extra_positions) * rates.ahrefs_units_per_serp_position
  const minUnits = rates.ahrefs_min_units_per_request ?? 0
  const overviewUnits = keywords > 0 ? Math.max(minUnits, keywords * rates.ahrefs_units_per_keyword) : 0
  const authorityUnits =
    modules.includes("authority") && ownUrls > 0
      ? Math.max(minUnits, ownUrls * rates.ahrefs_units_per_url)
      : 0

  const contentAnalysis = modules.includes("topics") || modules.includes("eeat")
  const aiCost = aiConfigured
    ? pages * rates.claude_eur_per_page + (contentAnalysis ? keywords * rates.claude_eur_per_keyword : 0)
    : 0

  return {
    pages,
    seconds: Math.round(pages * rates.seconds_per_page + keywords * rates.seconds_per_keyword),
    ahrefs_units: Math.ceil(serpUnits + overviewUnits + authorityUnits),
    ai_cost_eur: aiCost,
  }
}

// --- API ------------------------------------------------------------------------------------

export const API_BASE = "/api/competitor-analyses"

/** Fout met de HTTP-status (0 = geen verbinding), zodat bijv. een 409 apart te tonen is. */
export class CompetitorAnalysisError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
    this.name = "CompetitorAnalysisError"
  }
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, { cache: "no-store", ...init })
  } catch {
    throw new CompetitorAnalysisError("Geen verbinding met de server.", 0)
  }
  const payload = (await response.json().catch(() => null)) as (T & { error?: string }) | null
  if (!response.ok) {
    throw new CompetitorAnalysisError(payload?.error?.trim() || "Er ging iets mis.", response.status)
  }
  return payload as T
}

function jsonInit(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }
}

const customerPath = (customerId: string) => `/customers/${encodeURIComponent(customerId)}`
const analysisPath = (analysisId: string) => `/analyses/${encodeURIComponent(analysisId)}`

/** Voorstel voor de wizard: zoekwoorden, databronnen en tarieven. Doet geen betaalde aanroep. */
export function fetchProposal(customerId: string) {
  return apiFetch<ProposalResponse>(`${customerPath(customerId)}/proposal`)
}

/** Start een analyse. 400 met een Nederlandse melding; 409 als er al een analyse loopt. */
export function startAnalysis(customerId: string, request: AnalysisCreateRequest) {
  return apiFetch<AnalysisDetail>(`${customerPath(customerId)}/analyses`, jsonInit("POST", request))
}

/** Analyses van een klant, nieuwste eerst. */
export function fetchAnalyses(customerId: string, limit?: number) {
  const query = limit ? `?${new URLSearchParams({ limit: String(limit) })}` : ""
  return apiFetch<AnalysisListResponse>(`${customerPath(customerId)}/analyses${query}`)
}

/** Status, tellers en zoekwoorden van één analyse (om te volgen). */
export function fetchAnalysis(analysisId: string) {
  return apiFetch<AnalysisDetail>(analysisPath(analysisId))
}

/** Volledig resultaat van één zoekwoord. */
export function fetchKeywordDetail(analysisId: string, keywordId: string) {
  return apiFetch<KeywordDetail>(`${analysisPath(analysisId)}/keywords/${encodeURIComponent(keywordId)}`)
}

export function cancelAnalysis(analysisId: string) {
  return apiFetch<AnalysisDetail>(`${analysisPath(analysisId)}/cancel`, { method: "POST" })
}

/** Verbeterpunt afvinken of weer openzetten. */
export function updateAction(actionId: string, done: boolean) {
  const body: ActionUpdate = { done }
  return apiFetch<ActionItem>(`/actions/${encodeURIComponent(actionId)}`, jsonInit("PATCH", body))
}
