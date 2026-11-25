/**
 * Zoekwoorden › Content gap per klant: types, hulpjes en de API-aanroepen.
 * Alles loopt via de proxy onder `/api/keywords`.
 *
 * De types volgen `backend/app/features/keywords/gap_schemas.py` één-op-één (zelfde veldnamen).
 * Een domein is een kale host zonder `www.`; tijdstippen ISO met tijdzone; Ahrefs in units.
 */

import { customerHref } from "@/lib/active-customer"

// --- Statussen ------------------------------------------------------------------------------

/** `idle` = nog nooit opgehaald. */
export type ContentGapStatus = "idle" | "pending" | "collecting" | "enriching" | "completed" | "failed"

export const ACTIVE_CONTENT_GAP_STATUSES: readonly ContentGapStatus[] = ["pending", "collecting", "enriching"]

/**
 * Waarom starten niet kan:
 * no_scan = nog geen voltooide concurrentenscan;
 * too_few_competitors = minder dan 2 concurrenten in de top 5;
 * ahrefs_not_configured = geen Ahrefs-sleutel.
 */
export type ContentGapBlocked = "no_scan" | "too_few_competitors" | "ahrefs_not_configured"

/** Minimaal aantal concurrenten in de top 10 voor een gap-zoekwoord. */
export const MIN_GAP_COMPETITORS = 2

// --- Antwoord -------------------------------------------------------------------------------

export type GapKeyword = {
  keyword: string
  volume: number | null
  kd: number | null
  /** Ahrefs-namen: commercial, informational, local, transactional, navigational, branded. */
  intents: string[]
  competitors_count: number
  /** Positie per concurrentdomein; null = niet in de top 10. */
  positions: Record<string, number | null>
  /** Positie van de klant; null = helemaal niet gevonden. */
  own_position: number | null
}

/** Antwoord van beide endpoints. Zonder resultaat is `has_result` false en `keywords` leeg. */
export type ContentGapOverview = {
  status: ContentGapStatus
  error: string | null
  blocked: ContentGapBlocked | null
  has_result: boolean
  customer_domain: string
  /** Domeinen in kolomvolgorde. */
  competitors: string[]
  /** Alle gevonden gap-zoekwoorden, ook de afgekapte. */
  found: number
  /** De uitgewerkte zoekwoorden, op volume aflopend. */
  keywords: GapKeyword[]
  units: number
  max_units: number
  started_at: string | null
  completed_at: string | null
  /** De concurrentenscan is nieuwer dan deze content gap. */
  stale: boolean
  warnings: string[]
}

// --- Hulpfuncties ---------------------------------------------------------------------------

export function isContentGapActive(status: ContentGapStatus) {
  return ACTIVE_CONTENT_GAP_STATUSES.includes(status)
}

export type IntentLabel = "Lokaal" | "Commercieel" | "Informatief" | "Navigatie"

/** Eén label per zoekwoord, in deze volgorde van voorrang; null bij een lege lijst. */
export function intentLabel(intents: string[]): IntentLabel | null {
  const set = new Set(intents.map((intent) => intent.toLowerCase()))
  if (set.has("local")) return "Lokaal"
  if (set.has("commercial") || set.has("transactional")) return "Commercieel"
  if (set.has("informational")) return "Informatief"
  if (set.has("navigational") || set.has("branded")) return "Navigatie"
  return null
}

// Tweedelige extensies (bijv. "co.uk"): die vallen in hun geheel weg.
const SECOND_LEVEL = new Set(["co", "com", "org", "net", "ac", "gov"])

/** Korte kolomkop: het domein zonder "www." en zonder extensie ("rankmeister.nl" → "rankmeister"). */
export function domainLabel(domain: string) {
  const parts = domain.trim().toLowerCase().replace(/^www\./, "").split(".")
  if (parts.length <= 1) return parts[0] ?? domain
  const cut = parts.length >= 3 && SECOND_LEVEL.has(parts[parts.length - 2]) ? 2 : 1
  return parts.slice(0, parts.length - cut).join(".")
}

/** Adres van het Content gap-scherm van een klant. */
export function contentGapHref(customerId: string) {
  return customerHref("zoekwoordContentGap", customerId)
}

// --- API ------------------------------------------------------------------------------------

const API_BASE = "/api/keywords"

export class ContentGapError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
    this.name = "ContentGapError"
  }
}

async function overviewFetch(path: string, init?: RequestInit): Promise<ContentGapOverview> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, { cache: "no-store", ...init })
  } catch {
    throw new ContentGapError("Geen verbinding met de server.", 0)
  }
  const payload = (await response.json().catch(() => null)) as
    | (ContentGapOverview & { error?: string; detail?: string })
    | null
  if (!response.ok) {
    // De proxy zet de `detail` van de backend om naar `error`.
    const message = payload?.error?.trim() || (typeof payload?.detail === "string" ? payload.detail.trim() : "")
    throw new ContentGapError(message || "Er ging iets mis.", response.status)
  }
  if (!payload) {
    throw new ContentGapError("Onverwacht antwoord van de server.", response.status)
  }
  return payload
}

const gapPath = (customerId: string) => `/customers/${encodeURIComponent(customerId)}/content-gap`

/** De content gap; zonder gegevens `status: "idle"` en `has_result: false`. */
export function fetchContentGap(customerId: string) {
  return overviewFetch(gapPath(customerId))
}

/** Start een run. 409 als er al een loopt, 400 als starten niet kan, 503 zonder wachtrij. */
export function startContentGap(customerId: string) {
  return overviewFetch(`${gapPath(customerId)}/start`, { method: "POST" })
}
