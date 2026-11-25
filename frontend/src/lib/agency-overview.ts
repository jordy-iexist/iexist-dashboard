// Bureau-overzicht: bureaubreed scherm met signalen en een klantentabel. Types (één-op-één met
// `backend/app/features/agency_overview/schemas.py`), de API-aanroepen via de proxy
// `/api/agency-overview` en het adres van een signaal. Vrij van React.

import { customerHref } from "@/lib/active-customer"
import { maandrapportHref } from "@/lib/monthly-report"
import { workBoardHref } from "@/lib/work-queue"

export const AGENCY_OVERVIEW_URL = "/dashboard/bureau"

const API_BASE = "/api/agency-overview"

// --- Types ----------------------------------------------------------------------------------

export type SignalKind = "daling" | "storing" | "werk" | "rapport"
export type SignalSeverity = "hoog" | "middel" | "laag"
export type SignalLinkType =
  | "customer_home"
  | "monthly_report"
  | "customer_profile"
  | "seo_geo"
  | "work_board"
  | "none"

export type SignalLink = {
  type: SignalLinkType
  customer_id: string | null
  /** "YYYY-MM", alleen bij `monthly_report`. */
  month: string | null
}

export type AgencySignal = {
  id: string
  kind: SignalKind
  severity: SignalSeverity
  /** Leeg bij een signaal over het hele bureau (bijv. een verlopen koppeling). */
  customer_id: string | null
  customer_name: string | null
  text: string
  link: SignalLink
}

export type RankState = "ok" | "not_configured" | "not_tracked" | "error" | "missing"

export type AgencyCustomer = {
  id: string
  name: string
  rank_state: RankState
  keywords: number | null
  top10: number | null
  /** Verschil in top 10 t.o.v. een maand geleden; positief = meer zoekwoorden in de top 10. */
  top10_delta: number | null
  open_tasks: number
  signal_count: number
}

export type AgencyKpis = {
  customers: number
  customers_attention: number
  open_tasks: number
  open_tasks_high: number
}

export type AgencyOverview = {
  generated_at: string
  /** ISO-weeknummer. */
  week: number
  /** Laatste momentopname van de posities; leeg als die nog nooit is opgehaald. */
  rankings_fetched_at: string | null
  kpis: AgencyKpis
  /** Van ernstig naar minder ernstig (volgorde van de backend). */
  signals: AgencySignal[]
  /** Klanten met signalen eerst, dan meer open taken, dan op naam (volgorde van de backend). */
  customers: AgencyCustomer[]
}

// --- Adressen -------------------------------------------------------------------------------

/** Adres waar een signaal naartoe linkt, of null (geen link of geen klant). */
export function signalHref(link: SignalLink): string | null {
  const id = link.customer_id?.trim() || null
  switch (link.type) {
    case "work_board":
      return workBoardHref({ customerId: id })
    case "none":
      return null
  }
  if (!id) return null
  switch (link.type) {
    case "customer_home":
      return customerHref("home", id)
    case "monthly_report":
      return maandrapportHref(id, link.month)
    case "customer_profile":
      return customerHref("profiel", id)
    case "seo_geo":
      return customerHref("seoGeo", id)
    default:
      return null
  }
}

// --- API ------------------------------------------------------------------------------------

export class AgencyOverviewError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
    this.name = "AgencyOverviewError"
  }
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, { cache: "no-store", ...init })
  } catch (error) {
    // Een afgebroken verzoek (AbortController) niet als verbindingsfout verpakken.
    if (error instanceof DOMException && error.name === "AbortError") throw error
    throw new AgencyOverviewError("Geen verbinding met de server.", 0)
  }
  const payload = (await response.json().catch(() => null)) as
    | (T & { error?: unknown; detail?: unknown })
    | null
  if (!response.ok || payload === null) {
    const message =
      (typeof payload?.error === "string" && payload.error.trim()) ||
      (typeof payload?.detail === "string" && payload.detail.trim()) ||
      "Er ging iets mis."
    throw new AgencyOverviewError(message, response.status)
  }
  return payload
}

export function fetchOverview(signal?: AbortSignal): Promise<AgencyOverview> {
  return apiFetch<AgencyOverview>("/overview", { signal })
}

/** Haalt de posities van alle klanten direct opnieuw op; geeft daarna het nieuwe overzicht. */
export function refreshRankings(signal?: AbortSignal): Promise<AgencyOverview> {
  return apiFetch<AgencyOverview>("/rankings/refresh", { method: "POST", signal })
}
