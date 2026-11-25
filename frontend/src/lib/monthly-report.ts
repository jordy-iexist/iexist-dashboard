/**
 * Maandrapport per klant: types, maandhulpjes, het adres van het scherm en de API-aanroepen.
 * Alles loopt via de proxy onder `/api/monthly-reports`.
 *
 * De types volgen `backend/app/features/monthly_report/schemas.py` één-op-één (zelfde
 * veldnamen). `month` is "YYYY-MM"; datums zijn ISO-tekst ("2026-11-01"), tijdstippen ISO met
 * tijdzone. Claude-verbruik in USD (`AiUsage.cost_usd`).
 */

import { customerHref } from "@/lib/active-customer"
import type { AiUsage } from "@/lib/competitor-analysis"

// --- Statussen en constanten ----------------------------------------------------------------

/** `draft` = nog geen run (eventueel wel handmatige cijfers). */
export type ReportStatus = "draft" | "pending" | "collecting" | "writing" | "completed" | "failed"

export const ACTIVE_REPORT_STATUSES: readonly ReportStatus[] = ["pending", "collecting", "writing"]

export type MetricKey = "clicks" | "top10" | "leads" | "ai_mentions"

/** De tegels en hun volgorde op het rapportvel. */
export const METRIC_ORDER: readonly MetricKey[] = ["clicks", "top10", "leads", "ai_mentions"]

/**
 * clicks: ok | not_configured | token_expired | no_property | property_inaccessible | no_data | error
 * top10, ai_mentions: ok | not_configured | not_tracked | out_of_window | error
 * leads: manual | not_connected
 */
export type MetricState =
  | "ok"
  | "manual"
  | "not_connected"
  | "not_configured"
  | "token_expired"
  | "no_property"
  | "property_inaccessible"
  | "not_tracked"
  | "out_of_window"
  | "no_data"
  | "error"

/** Toestanden waarbij het cijfer op het vel als getal staat. */
export const USABLE_METRIC_STATES: readonly MetricState[] = ["ok", "manual"]

/** Toestanden waarbij de bron (nog) niet aan de klant hangt. */
export const NOT_LINKED_METRIC_STATES: readonly MetricState[] = [
  "not_configured",
  "token_expired",
  "no_property",
  "property_inaccessible",
  "not_tracked",
  "not_connected",
]

export const LEADS_MAX = 1_000_000

export const MONTH_PARAM = "maand"

/** In de eerste zoveel dagen van een maand is de vorige maand de standaard. */
const PREVIOUS_MONTH_DAYS = 7

/** Zo ver terug kan de maandkiezer (Search Console bewaart 16 maanden). */
export const MAX_MONTHS_BACK = 16

// --- data: momentopname ---------------------------------------------------------------------

/** Periode waarover de Search Console-cijfers gaan (bij een lopende maand korter). */
export type Period = {
  start: string
  end: string
  days: number
  /** false = de maand is nog niet (helemaal) beschikbaar in Search Console. */
  complete: boolean
}

/** Eén cijfertegel. Velden die bij een tegel niet horen zijn `null`. */
export type Metric = {
  state: MetricState
  message: string | null
  value: number | null
  previous: number | null
  delta: number | null
  /** Alleen clicks; null als de vorige periode 0 was. */
  delta_pct: number | null
  /** top10: aantal gevolgde zoekwoorden; ai_mentions: aantal prompts. */
  total: number | null
  /** Alleen clicks. */
  impressions: number | null
  property: string | null
  property_source: "manual" | "auto" | null
  /** top10 en ai_mentions: moment waarop ProRankTracker is uitgelezen. */
  captured_at: string | null
  /** Alleen leads: waar `previous` vandaan komt. */
  previous_source: "manual" | "previous_report" | null
}

export type Metrics = Record<MetricKey, Metric>

export type WorkExample = {
  title: string
  path: string | null
}

/** Aanpassingen van één onderwerp (bijv. alle meta descriptions) samengenomen. */
export type WorkGroup = {
  id: string
  topic: string
  label: string
  count: number
  pages: number
  /** Aantal dat live is teruggezien; null bij openstaand werk. */
  verified: number | null
  examples: WorkExample[]
}

export type WorkBlog = {
  id: string
  title: string
  published_at: string
  url: string | null
}

export type WorkBrief = {
  id: string
  keyword: string
  /** true = de brief is voor een pagina die nog niet bestaat. */
  new_page: boolean
}

export type QuickWin = {
  id: string
  keyword: string
  position: number | null
  volume: number | null
}

/** Wat er in de maand is gedaan (id's W1, W2, …). */
export type Work = {
  changes: WorkGroup[]
  blogs: WorkBlog[]
  briefs: WorkBrief[]
}

/** Openstaand werk waaruit de agent "Volgende maand" kiest (id's N1, N2, …). */
export type Upcoming = {
  approved_changes: WorkGroup[]
  briefs: WorkBrief[]
  quick_wins: QuickWin[]
}

export type ReportData = {
  version: number
  month: string
  collected_at: string
  /** null als Search Console voor deze maand nog niets heeft. */
  period: Period | null
  previous: Period | null
  metrics: Metrics
  work: Work
  upcoming: Upcoming
}

// --- report: tekst van de agent -------------------------------------------------------------

export type ReportItem = {
  text: string
  refs: string[]
}

/** Opmerking voor de specialist. `agent` = door Claude gemeld, `check` = controle in code. */
export type ReviewNote = {
  text: string
  source: "agent" | "check"
}

/** `version` telt op bij elke nieuwe tekst. */
export type ReportText = {
  version: number
  summary: string[]
  work_done: ReportItem[]
  next_month: ReportItem[]
  review_notes: ReviewNote[]
}

// --- Aanvragen en antwoord ------------------------------------------------------------------

/**
 * Aanvragen zoals het scherm ze toont (bij elk lezen berekend uit de handmatige cijfers).
 * `previous` komt uit het handmatig ingevulde cijfer, anders uit het rapport van de vorige maand.
 */
export type Leads = {
  value: number | null
  previous: number | null
  previous_source: "manual" | "previous_report" | null
  updated_at: string | null
}

/** Body van `PATCH …/manual`; `null` wist het cijfer. */
export type ManualUpdate = {
  leads: number | null
  leads_previous: number | null
}

/** Antwoord van alle endpoints. Zonder rapport: `id = null` en `status = "draft"`. */
export type MonthlyReport = {
  id: string | null
  customer_website_id: string
  month: string
  status: ReportStatus
  error_message: string | null
  model: string | null
  ai_usage: AiUsage
  created_at: string | null
  updated_at: string | null
  completed_at: string | null
  /** De tegel "Aanvragen" toont altijd dit, niet `data.metrics.leads`. */
  leads: Leads
  /** true = de aanvragen zijn gewijzigd nadat de tekst is geschreven. */
  text_outdated: boolean
  data: ReportData | null
  report: ReportText | null
}

// --- Maanden --------------------------------------------------------------------------------

const MONTH_PATTERN = /^(\d{4})-(0[1-9]|1[0-2])$/

const amsterdamParts = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Europe/Amsterdam",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
})

const monthLabelFormat = new Intl.DateTimeFormat("nl-NL", { month: "long", year: "numeric", timeZone: "UTC" })
const monthNameFormat = new Intl.DateTimeFormat("nl-NL", { month: "long", timeZone: "UTC" })

function splitMonth(month: string) {
  const [year, index] = month.split("-").map(Number)
  return { year, index }
}

function toMonth(year: number, index: number) {
  return `${String(year).padStart(4, "0")}-${String(index).padStart(2, "0")}`
}

function monthDate(month: string, day = 1) {
  const { year, index } = splitMonth(month)
  return new Date(Date.UTC(year, index - 1, day))
}

/** Datum in Amsterdam: jaar, maand (1–12) en dag. */
function amsterdamDate(now: Date) {
  const parts = Object.fromEntries(amsterdamParts.formatToParts(now).map((part) => [part.type, part.value]))
  return { year: Number(parts.year), month: Number(parts.month), day: Number(parts.day) }
}

/** "2026-11" uit `?maand=`; null als het ontbreekt of geen geldige maand is. */
export function parseMonth(value: string | string[] | undefined | null): string | null {
  const raw = (Array.isArray(value) ? value[0] : value)?.trim()
  return raw && MONTH_PATTERN.test(raw) ? raw : null
}

/** Maand verschuiven: `shiftMonth("2026-01", -1)` → "2025-12". */
export function shiftMonth(month: string, delta: number) {
  const { year, index } = splitMonth(month)
  const total = year * 12 + (index - 1) + delta
  return toMonth(Math.floor(total / 12), (total % 12) + 1)
}

/** De lopende maand in Amsterdam. */
export function currentMonth(now: Date) {
  const { year, month } = amsterdamDate(now)
  return toMonth(year, month)
}

/** De lopende maand; in de eerste 7 dagen van een maand de vorige. */
export function defaultMonth(now: Date) {
  const { year, month, day } = amsterdamDate(now)
  const current = toMonth(year, month)
  return day <= PREVIOUS_MONTH_DAYS ? shiftMonth(current, -1) : current
}

/** De oudste maand die de kiezer toont. */
export function oldestMonth(now: Date) {
  return shiftMonth(currentMonth(now), -MAX_MONTHS_BACK)
}

/** Niet in de toekomst en niet verder terug dan `MAX_MONTHS_BACK` maanden. */
export function isMonthInRange(month: string, now: Date) {
  return month <= currentMonth(now) && month >= oldestMonth(now)
}

/** "november 2026". */
export function monthLabel(month: string) {
  return monthLabelFormat.format(monthDate(month))
}

/** Alleen de maandnaam: "oktober". */
export function monthName(month: string) {
  return monthNameFormat.format(monthDate(month))
}

/** Aantal dagen in de maand. */
function daysInMonth(month: string) {
  const { year, index } = splitMonth(month)
  return new Date(Date.UTC(year, index, 0)).getUTCDate()
}

const dayMonthFormat = new Intl.DateTimeFormat("nl-NL", { day: "numeric", month: "long", timeZone: "UTC" })
const dayMonthYearFormat = new Intl.DateTimeFormat("nl-NL", {
  day: "numeric",
  month: "long",
  year: "numeric",
  timeZone: "UTC",
})

function isoDate(value: string) {
  const date = new Date(`${value.slice(0, 10)}T00:00:00Z`)
  return Number.isNaN(date.getTime()) ? null : date
}

/** "22 november"; null bij een ongeldige datum. */
export function formatDayMonth(value: string) {
  const date = isoDate(value)
  return date ? dayMonthFormat.format(date) : null
}

/**
 * Periode van de cijfers: "1 – 22 november 2026"; over twee maanden "28 oktober – 3 november 2026".
 * Zonder periode de hele maand.
 */
export function periodLabel(period: Pick<Period, "start" | "end"> | null | undefined, month: string) {
  const start = period ? isoDate(period.start) : monthDate(month)
  const end = period ? isoDate(period.end) : monthDate(month, daysInMonth(month))
  if (!start || !end) return monthLabel(month)
  const endText = dayMonthYearFormat.format(end)
  if (start.getUTCFullYear() !== end.getUTCFullYear()) return `${dayMonthYearFormat.format(start)} – ${endText}`
  if (start.getUTCMonth() !== end.getUTCMonth()) return `${dayMonthFormat.format(start)} – ${endText}`
  return `${start.getUTCDate()} – ${endText}`
}

// --- Hulpfuncties ---------------------------------------------------------------------------

export function isReportActive(status: ReportStatus) {
  return ACTIVE_REPORT_STATUSES.includes(status)
}

/** Het scherm van een klant; zonder maand de standaardmaand. */
export function maandrapportHref(customerId: string, month?: string | null) {
  const base = customerHref("maandrapport", customerId)
  return month ? `${base}?${new URLSearchParams({ [MONTH_PARAM]: month })}` : base
}

// --- API ------------------------------------------------------------------------------------

const API_BASE = "/api/monthly-reports"

export class MonthlyReportError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
    this.name = "MonthlyReportError"
  }
}

async function reportFetch(path: string, init?: RequestInit): Promise<MonthlyReport> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, { cache: "no-store", ...init })
  } catch {
    throw new MonthlyReportError("Geen verbinding met de server.", 0)
  }
  const payload = (await response.json().catch(() => null)) as (MonthlyReport & { error?: string }) | null
  if (!response.ok) {
    throw new MonthlyReportError(payload?.error?.trim() || "Er ging iets mis.", response.status)
  }
  if (!payload) {
    throw new MonthlyReportError("Onverwacht antwoord van de server.", response.status)
  }
  return payload
}

const reportPath = (customerId: string, month: string) =>
  `/customers/${encodeURIComponent(customerId)}/reports/${encodeURIComponent(month)}`

/** Het rapport van een maand; zonder rapport `id: null` en `status: "draft"`. */
export function fetchReport(customerId: string, month: string) {
  return reportFetch(reportPath(customerId, month))
}

/** Start het rapport. 409 als het al loopt of al bestaat, 503 zonder Claude-sleutel of wachtrij. */
export function startReport(customerId: string, month: string) {
  return reportFetch(reportPath(customerId, month), { method: "POST" })
}

/** Cijfers en tekst opnieuw; kan vanaf `completed` of `failed`. */
export function regenerateReport(customerId: string, month: string) {
  return reportFetch(`${reportPath(customerId, month)}/regenerate`, { method: "POST" })
}

/** Aanvragen handmatig vastleggen; kan altijd, ook zonder rapport en tijdens een run. */
export function saveManual(customerId: string, month: string, update: ManualUpdate) {
  return reportFetch(`${reportPath(customerId, month)}/manual`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(update),
  })
}
