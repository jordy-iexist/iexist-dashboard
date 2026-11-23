import { unstable_noStore as noStore } from "next/cache"

import { getBackendApiUrl, getBackendAuthorizationValue } from "@/lib/backend-api"
import type { AnalysisListItem, AnalysisListResponse } from "@/lib/competitor-analysis"

/** Analyses voor een server-component; `failed` = ophalen mislukt (lijst is dan leeg). */
export type RecentAnalyses = {
  items: AnalysisListItem[]
  failed: boolean
}

// Laatste analyses van een klant, nieuwste eerst. Faalt nooit hard: zonder autorisatie,
// bij een HTTP-fout of een onverwacht antwoord komt er een lege lijst met `failed` terug.
export async function fetchRecentAnalyses(customerId: string, limit: number): Promise<RecentAnalyses> {
  noStore()

  const failed: RecentAnalyses = { items: [], failed: true }
  const authorization = await getBackendAuthorizationValue()
  if (!authorization) {
    return failed
  }

  try {
    const query = new URLSearchParams({ limit: String(limit) })
    const response = await fetch(
      `${getBackendApiUrl()}/api/competitor-analyses/customers/${encodeURIComponent(customerId)}/analyses?${query}`,
      {
        method: "GET",
        headers: {
          Authorization: authorization,
        },
        cache: "no-store",
      }
    )

    if (!response.ok) {
      return failed
    }

    const payload = (await response.json().catch(() => null)) as AnalysisListResponse | null
    return Array.isArray(payload?.items) ? { items: payload.items, failed: false } : failed
  } catch {
    return failed
  }
}
