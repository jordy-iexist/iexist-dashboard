import { apiFetch, type ScanStatus } from "@/lib/launch-checklist"

// --- sitemap-monitor (phase = 6) -------------------------------------------

export type SitemapChangeKind = "new" | "changed" | "removed"

export type SitemapChange = {
  kind: SitemapChangeKind
  url: string
  lastmod: string | null
  detected_at: string
}

export type SitemapMonitorStatus = {
  customer_id: string
  /** Schakelaar per klant voor de dagelijkse controle. */
  enabled: boolean
  /** Globale noodrem (SITEMAP_MONITOR_ENABLED); uit = geen dagelijkse controle voor wie dan ook. */
  global_enabled: boolean
  /** Voltooide nulmeting (fase 1) aanwezig; zonder die wordt de klant overgeslagen. */
  has_nulmeting: boolean
  /** De doorlopende monitor-scan; null tot de eerste run met nieuwe of gewijzigde pagina's. */
  scan_id: string | null
  scan_status: ScanStatus | null
  /** Alleen true zolang de monitor-scan echt pagina's verwerkt. */
  running: boolean
  checked_at: string | null
  changed_at: string | null
  last_error: string | null
  /** Aantal URL's in de laatst bekende sitemap-stand; 0 = nog geen uitgangssituatie. */
  total_urls: number
  has_lastmod: boolean
  /** Nieuwste eerst, hooguit 300. */
  recent_changes: SitemapChange[]
  open_issues: number
}

export const SITEMAP_CHANGE_LABELS: Record<SitemapChangeKind, string> = {
  new: "Nieuw",
  changed: "Gewijzigd",
  removed: "Verwijderd",
}

function monitorPath(customerId: string) {
  return `/customers/${encodeURIComponent(customerId)}/sitemap-monitor`
}

export function fetchSitemapMonitor(customerId: string) {
  return apiFetch<SitemapMonitorStatus>(monitorPath(customerId))
}

export function updateSitemapMonitor(customerId: string, enabled: boolean) {
  return apiFetch<SitemapMonitorStatus>(monitorPath(customerId), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  })
}

/** Zet één controle in de wachtrij. Geeft de stand van vóór de run terug. */
export function runSitemapMonitor(customerId: string) {
  return apiFetch<SitemapMonitorStatus>(`${monitorPath(customerId)}/run`, { method: "POST" })
}
