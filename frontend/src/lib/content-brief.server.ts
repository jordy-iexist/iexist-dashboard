import { unstable_noStore as noStore } from "next/cache"

import { getBackendApiUrl, getBackendAuthorizationValue } from "@/lib/backend-api"
import type { ContentBriefListItem, ContentBriefListResponse } from "@/lib/content-brief"

/** Content briefs voor een server-component; `failed` = ophalen mislukt (lijst is dan leeg). */
export type RecentBriefs = {
  items: ContentBriefListItem[]
  failed: boolean
}

// Content briefs van een klant, laatst bijgewerkte eerst. Faalt nooit hard: zonder autorisatie,
// bij een HTTP-fout of een onverwacht antwoord komt er een lege lijst met `failed` terug.
export async function fetchRecentBriefs(customerId: string, limit: number): Promise<RecentBriefs> {
  noStore()

  const failed: RecentBriefs = { items: [], failed: true }
  const authorization = await getBackendAuthorizationValue()
  if (!authorization) {
    return failed
  }

  try {
    const query = new URLSearchParams({ limit: String(limit) })
    const response = await fetch(
      `${getBackendApiUrl()}/api/competitor-analyses/customers/${encodeURIComponent(customerId)}/briefs?${query}`,
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

    const payload = (await response.json().catch(() => null)) as ContentBriefListResponse | null
    return Array.isArray(payload?.items) ? { items: payload.items, failed: false } : failed
  } catch {
    return failed
  }
}
