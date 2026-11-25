// Werkvoorraad: bureaubreed kanban-bord met kaarten uit de scan, analyses, Search Console,
// Aanpassingen en eigen taken. Types, API-aanroepen (via de proxy `/api/work-queue`) en pure helpers.
// Vrij van React. Importeert bewust niets uit `active-customer.ts`, `competitor-analysis.ts` of
// `site-changes.ts`, om importcycli te voorkomen (de klantkiezer mag dit bestand importeren).

import { SEO_GEO_BASE_URL, seoGeoSectionHref, type SeoGeoSlug } from "@/lib/seo-geo-sections"

// --- Types ----------------------------------------------------------------------------------

export type WorkStatus = "todo" | "doing" | "review" | "done"
export type WorkSource = "scan" | "analysis" | "search_console" | "site_changes" | "manual"
export type WorkKind = "ctr" | "techniek" | "content" | "links" | "update" | "rapport"
export type WorkSeverity = "hoog" | "middel" | "laag"

export type WorkCard = {
  id: string
  customer_id: string
  customer_name: string
  source: WorkSource
  kind: WorkKind
  title: string
  item_count: number
  unit: string | null
  severity: WorkSeverity
  status: WorkStatus
  position: number
  assignee_id: string | null
  assignee_name: string | null
  has_note: boolean
  resolved_by_source: boolean
  done_at: string | null
  created_at: string
}

export type WorkColumn = {
  status: WorkStatus
  label: string
  count: number
  cards: WorkCard[]
}

export type WorkTotals = {
  todo: number
  doing: number
  review: number
  done: number
  unassigned: number
}

export type WorkBoardCustomer = { id: string; name: string; open_count: number }
export type WorkBoardUser = { id: string; name: string; email: string; open_count: number }

export type WorkBoard = {
  week_start: string
  /** Altijd in de volgorde todo, doing, review, done. */
  columns: WorkColumn[]
  totals: WorkTotals
  /** Ongefilterd: alle klanten, ook als er op klant gefilterd is. */
  customers: WorkBoardCustomer[]
  /** Ongefilterd: alle medewerkers. */
  users: WorkBoardUser[]
}

export type WorkCardItem = {
  key: string
  title: string
  url: string | null
  path: string | null
  severity: string | null
}

/** Waar een automatische kaart vandaan komt; `null` bij een eigen taak. */
export type SourceLink =
  | { source: "scan"; customer_id: string; phase: 1 | 2 | 3 | 4 | 6; issue_type: string }
  | { source: "analysis"; customer_id: string; analysis_id: string; keyword_id: string }
  | { source: "search_console"; customer_id: string }
  | { source: "site_changes"; customer_id: string; url: string }

export type WorkCardDetail = WorkCard & {
  note: string | null
  items: WorkCardItem[]
  source_link: SourceLink | null
  done_by_name: string | null
  created_by_name: string | null
}

/**
 * Wijziging van een kaart. `after_id` = de kaart direct erboven, `before_id` = de kaart direct
 * eronder (de backend plaatst relatief). `assignee_id: null` haalt de toewijzing weg.
 */
export type WorkCardPatch = {
  status?: WorkStatus
  after_id?: string
  before_id?: string
  assignee_id?: string | null
  note?: string | null
  title?: string
  kind?: WorkKind
}

export type WorkCardCreate = {
  title: string
  customer_id: string
  kind: WorkKind
  status?: WorkStatus
  assignee_id?: string | null
  note?: string | null
}

/**
 * Filters uit het adres. `customerId` en `assigneeId` filtert de backend (`assigneeId` mag
 * `UNASSIGNED` zijn), `kind` en `source` filtert de browser, `cardId` opent het paneel.
 */
export type BoardFilters = {
  customerId: string | null
  assigneeId: string | null
  kind: WorkKind | null
  source: WorkSource | null
  cardId: string | null
}

// --- Constanten -----------------------------------------------------------------------------

export const WORK_BOARD_URL = "/dashboard/werkvoorraad"

/** Namen van de queryparameters van het bord. */
export const BOARD_PARAMS = {
  customer: "klant",
  assignee: "medewerker",
  kind: "soort",
  source: "bron",
  card: "taak",
} as const

/** Waarde van `medewerker` (en `assignee_id` in de backend) voor "niet toegewezen". */
export const UNASSIGNED = "none"

export const STATUS_ORDER: readonly WorkStatus[] = ["todo", "doing", "review", "done"]

export const STATUS_LABELS: Record<WorkStatus, string> = {
  todo: "Te doen",
  doing: "Bezig",
  review: "Review",
  done: "Klaar deze week",
}

export const SOURCE_LABELS: Record<WorkSource, string> = {
  scan: "SEO/GEO-scan",
  analysis: "Concurrentieanalyse",
  search_console: "Search Console",
  site_changes: "Aanpassingen",
  manual: "Eigen taak",
}

export const SOURCES: readonly WorkSource[] = ["scan", "analysis", "search_console", "site_changes", "manual"]

export const KINDS: readonly { value: WorkKind; label: string }[] = [
  { value: "ctr", label: "CTR" },
  { value: "techniek", label: "Techniek" },
  { value: "content", label: "Content" },
  { value: "links", label: "Links" },
  { value: "update", label: "Update" },
  { value: "rapport", label: "Rapport" },
]

export const KIND_LABELS = Object.fromEntries(KINDS.map((kind) => [kind.value, kind.label])) as Record<
  WorkKind,
  string
>

export function isWorkStatus(value: unknown): value is WorkStatus {
  return STATUS_ORDER.includes(value as WorkStatus)
}

export function isWorkKind(value: unknown): value is WorkKind {
  return KINDS.some((kind) => kind.value === value)
}

export function isWorkSource(value: unknown): value is WorkSource {
  return SOURCES.includes(value as WorkSource)
}

// --- API ------------------------------------------------------------------------------------

export const API_BASE = "/api/work-queue"

/** Fout met de HTTP-status (0 = geen verbinding), zodat bijv. een 409 apart te tonen is. */
export class WorkQueueError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
    this.name = "WorkQueueError"
  }
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, { cache: "no-store", ...init })
  } catch (error) {
    // Een afgebroken verzoek (AbortController) niet als verbindingsfout verpakken.
    if (error instanceof DOMException && error.name === "AbortError") throw error
    throw new WorkQueueError("Geen verbinding met de server.", 0)
  }
  const payload = (await response.json().catch(() => null)) as
    | (T & { error?: unknown; detail?: unknown })
    | null
  if (!response.ok) {
    const message =
      (typeof payload?.error === "string" && payload.error.trim()) ||
      (typeof payload?.detail === "string" && payload.detail.trim()) ||
      "Er ging iets mis."
    throw new WorkQueueError(message, response.status)
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

const cardPath = (cardId: string) => `/cards/${encodeURIComponent(cardId)}`

/** Het bord; filtert in de backend alleen op klant en medewerker (`UNASSIGNED` = niet toegewezen). */
export function fetchBoard(
  filters: Partial<Pick<BoardFilters, "customerId" | "assigneeId">>,
  signal?: AbortSignal
) {
  const query = new URLSearchParams()
  if (filters.customerId) query.set("customer_id", filters.customerId)
  if (filters.assigneeId) query.set("assignee_id", filters.assigneeId)
  const search = query.toString()
  return apiFetch<WorkBoard>(`/board${search ? `?${search}` : ""}`, { signal })
}

/** Eén kaart met notitie, punten en bronlink. */
export function fetchCard(cardId: string, signal?: AbortSignal) {
  return apiFetch<WorkCardDetail>(cardPath(cardId), { signal })
}

/** Nieuwe eigen taak. */
export function createCard(body: WorkCardCreate) {
  return apiFetch<WorkCardDetail>("/cards", jsonInit("POST", body))
}

/** Verplaatsen, toewijzen, notitie of titel wijzigen. 409 o.a. als een Aanpassingen-kaart nog open punten heeft. */
export function updateCard(cardId: string, patch: WorkCardPatch) {
  return apiFetch<WorkCardDetail>(cardPath(cardId), jsonInit("PATCH", patch))
}

export function deleteCard(cardId: string) {
  return apiFetch<{ ok: true }>(cardPath(cardId), { method: "DELETE" })
}

// --- Adres ----------------------------------------------------------------------------------

/** Pad naar het bord met de gegeven filters; lege waarden worden weggelaten. */
export function workBoardHref(filters: Partial<BoardFilters> & { cardId?: string | null } = {}): string {
  const query = new URLSearchParams()
  const entries: [string, string | null | undefined][] = [
    [BOARD_PARAMS.customer, filters.customerId],
    [BOARD_PARAMS.assignee, filters.assigneeId],
    [BOARD_PARAMS.kind, filters.kind],
    [BOARD_PARAMS.source, filters.source],
    [BOARD_PARAMS.card, filters.cardId],
  ]
  for (const [key, value] of entries) {
    const trimmed = value?.trim()
    if (trimmed) query.set(key, trimmed)
  }
  const search = query.toString()
  return search ? `${WORK_BOARD_URL}?${search}` : WORK_BOARD_URL
}

/** Filters uit `useSearchParams()` of `URLSearchParams`; ongeldige `soort`/`bron` worden genegeerd. */
export function parseBoardFilters(searchParams: { get(name: string): string | null }): BoardFilters {
  const read = (key: string) => searchParams.get(key)?.trim() || null
  const kind = read(BOARD_PARAMS.kind)
  const source = read(BOARD_PARAMS.source)
  return {
    customerId: read(BOARD_PARAMS.customer),
    assigneeId: read(BOARD_PARAMS.assignee),
    kind: isWorkKind(kind) ? kind : null,
    source: isWorkSource(source) ? source : null,
    cardId: read(BOARD_PARAMS.card),
  }
}

// --- Bord-bewerkingen -----------------------------------------------------------------------

/**
 * Verplaatst een kaart (immutabel) naar `toStatus` op plek `toIndex` (index ná het weghalen uit
 * de oude plek, zoals sleepbibliotheken die geven). Tellers schuiven mee. Bij binnenkomst in
 * Klaar krijgt de kaart `done_at = now`; bij vertrek uit Klaar wordt `done_at` leeg.
 * Onbekende kaart of kolom: de kolommen komen ongewijzigd terug.
 */
export function moveCard(
  columns: WorkColumn[],
  cardId: string,
  toStatus: WorkStatus,
  toIndex: number,
  now: Date = new Date()
): WorkColumn[] {
  const from = columns.findIndex((column) => column.cards.some((card) => card.id === cardId))
  const to = columns.findIndex((column) => column.status === toStatus)
  if (from === -1 || to === -1) return columns

  const card = columns[from].cards.find((item) => item.id === cardId)!
  const moved: WorkCard = { ...card, status: toStatus }
  if (toStatus === "done" && card.status !== "done") moved.done_at = now.toISOString()
  if (toStatus !== "done" && card.status === "done") moved.done_at = null

  return columns.map((column, index) => {
    if (index !== from && index !== to) return column
    let cards = index === from ? column.cards.filter((item) => item.id !== cardId) : column.cards
    if (index === to) {
      const at = Math.max(0, Math.min(Math.trunc(toIndex), cards.length))
      cards = [...cards.slice(0, at), moved, ...cards.slice(at)]
    }
    const count = from === to ? column.count : index === from ? Math.max(0, column.count - 1) : column.count + 1
    return { ...column, cards, count }
  })
}

/** Buren van de kaart op `index`: `after_id` = erboven, `before_id` = eronder (of undefined). */
export function neighbourIds(
  cards: readonly Pick<WorkCard, "id">[],
  index: number
): { after_id?: string; before_id?: string } {
  return {
    after_id: index > 0 ? cards[index - 1]?.id : undefined,
    before_id: cards[index + 1]?.id,
  }
}

// --- Bronlink -------------------------------------------------------------------------------

const SCAN_PHASE_SLUGS: Record<1 | 2 | 3 | 4 | 6, SeoGeoSlug> = {
  1: "nulmeting",
  2: "geo-checklist",
  3: "content",
  4: "kwartaal",
  6: "monitor",
}

// Gelijk aan `KEYWORD_PARAM` in `competitor-analysis.ts` (niet geïmporteerd, zie bovenaan).
const ANALYSIS_KEYWORD_PARAM = "zoekwoord"

/** Route in het dashboard waar de bron van een kaart staat, of null (eigen taak). */
export function sourceHref(link: SourceLink | null): string | null {
  if (!link) return null
  const customerId = encodeURIComponent(link.customer_id)
  switch (link.source) {
    case "scan": {
      const slug = SCAN_PHASE_SLUGS[link.phase]
      return slug ? seoGeoSectionHref(link.customer_id, slug) : `${SEO_GEO_BASE_URL}/${customerId}`
    }
    case "analysis": {
      const base = `/dashboard/klanten/${customerId}/analyses/${encodeURIComponent(link.analysis_id)}`
      if (!link.keyword_id) return base
      return `${base}?${new URLSearchParams({ [ANALYSIS_KEYWORD_PARAM]: link.keyword_id })}`
    }
    case "search_console":
      return `/dashboard/klanten/${customerId}/search-console`
    case "site_changes": {
      // Aanpassingen kiest de pagina via `?url=` (zie `ChangesWorkspace`).
      const base = seoGeoSectionHref(link.customer_id, "aanpassingen")
      return link.url ? `${base}?${new URLSearchParams({ url: link.url })}` : base
    }
    default:
      return null
  }
}

// --- Weergave -------------------------------------------------------------------------------

/** Eerste letter van een naam (hoofdletter), of "?" zonder naam. */
export function initialOf(name: string | null | undefined): string {
  const first = name?.trim().charAt(0)
  return first ? first.toLocaleUpperCase("nl-NL") : "?"
}

// Volledige klassennamen, zodat Tailwind ze vindt. Leesbaar in licht en donker.
const AVATAR_TONES = [
  "bg-sky-100 text-sky-800 dark:bg-sky-900/60 dark:text-sky-200",
  "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/60 dark:text-emerald-200",
  "bg-amber-100 text-amber-800 dark:bg-amber-900/60 dark:text-amber-200",
  "bg-violet-100 text-violet-800 dark:bg-violet-900/60 dark:text-violet-200",
  "bg-rose-100 text-rose-800 dark:bg-rose-900/60 dark:text-rose-200",
  "bg-teal-100 text-teal-800 dark:bg-teal-900/60 dark:text-teal-200",
] as const

/** Vaste kleur per medewerker (hash over het id). */
export function avatarTone(userId: string | null | undefined): string {
  if (!userId) return "bg-muted text-muted-foreground"
  let hash = 0
  for (let index = 0; index < userId.length; index += 1) {
    hash = (hash * 31 + userId.charCodeAt(index)) >>> 0
  }
  return AVATAR_TONES[hash % AVATAR_TONES.length]
}

const dayMonthFormat = new Intl.DateTimeFormat("nl-NL", {
  day: "numeric",
  month: "short",
  timeZone: "Europe/Amsterdam",
})

/** "14 nov" (zonder jaar en zonder punt), of "" bij een ongeldige datum. */
export function formatDayMonth(iso: string | null | undefined): string {
  if (!iso) return ""
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ""
  return dayMonthFormat
    .formatToParts(date)
    .map((part) => (part.type === "month" ? part.value.replace(/\.$/, "") : part.value))
    .join("")
}

/**
 * Onderregel van een kaart. Klaar: "✓ opgelost 14 nov" (bron loste het op) of "✓ afgerond 14 nov".
 * Anders: "{bron} · {n} {eenheid}" bij automatische kaarten, alleen "Eigen taak" bij een eigen taak.
 */
export function cardMeta(
  card: Pick<WorkCard, "source" | "status" | "item_count" | "unit" | "resolved_by_source" | "done_at">
): string {
  if (card.status === "done") {
    const verb = card.resolved_by_source ? "opgelost" : "afgerond"
    const day = formatDayMonth(card.done_at)
    return day ? `✓ ${verb} ${day}` : `✓ ${verb}`
  }
  const label = SOURCE_LABELS[card.source]
  if (card.source === "manual" || !card.unit || card.item_count <= 0) return label
  return `${label} · ${card.item_count} ${card.unit}`
}
