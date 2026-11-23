import { notFound, redirect } from "next/navigation"
import { unstable_noStore as noStore } from "next/cache"

import {
  getBackendApiUrl,
  getBackendAuthorizationValue,
} from "@/lib/backend-api"
import {
  type CustomerContentGap,
  type CustomerImprovements,
  type CustomerQuickWinRow,
  type CustomerQuickWins,
  type CustomerQuickWinsState,
  type CustomerRankings,
  type CustomerRankingsState,
  type QuickWinChance,
  type QuickWinSource,
  type CustomersResponse,
  type CustomerWebsiteDetail,
  type CustomerWebsiteListItem,
} from "@/lib/customer-types"

// Klantenlijst voor server-componenten (o.a. de sidebar). Faalt nooit hard:
// zonder autorisatie of bij een fout komt er een lege lijst terug.
export async function fetchCustomerList(): Promise<CustomerWebsiteListItem[]> {
  noStore()

  const authorization = await getBackendAuthorizationValue()
  if (!authorization) {
    return []
  }

  try {
    const response = await fetch(`${getBackendApiUrl()}/api/customers`, {
      method: "GET",
      headers: {
        Authorization: authorization,
      },
      cache: "no-store",
    })

    if (!response.ok) {
      return []
    }

    const payload = (await response.json().catch(() => null)) as
      | CustomersResponse
      | null
    return Array.isArray(payload?.websites) ? payload.websites : []
  } catch {
    return []
  }
}

export async function fetchCustomerDetail(
  customerId: string
): Promise<CustomerWebsiteDetail> {
  noStore()

  const authorization = await getBackendAuthorizationValue()
  if (!authorization) {
    redirect("/login")
  }

  let customer: CustomerWebsiteDetail | null = null
  try {
    const response = await fetch(
      `${getBackendApiUrl()}/api/customers/${encodeURIComponent(customerId)}`,
      {
        method: "GET",
        headers: {
          Authorization: authorization,
        },
        cache: "no-store",
      }
    )

    if (!response.ok) {
      notFound()
    }

    customer = (await response.json().catch(() => null)) as CustomerWebsiteDetail | null
  } catch {
    notFound()
  }

  if (!customer?.id) {
    notFound()
  }

  return customer
}

const RANKING_STATES: CustomerRankingsState[] = [
  "ok",
  "not_configured",
  "not_tracked",
  "error",
]

function numberOr<T>(value: unknown, fallback: T): number | T {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback
}

function stringOrNull(value: unknown): string | null {
  return typeof value === "string" && value ? value : null
}

function emptyRankings(): CustomerRankings {
  return {
    state: "error",
    message: null,
    fetched_at: null,
    keywords: 0,
    ranked: 0,
    avg_position: null,
    avg_position_delta: null,
    top3: 0,
    top3_delta: null,
    content_gaps: [],
    content_gaps_total: 0,
  }
}

function parseContentGaps(value: unknown): CustomerContentGap[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((item) => {
    if (!item || typeof item !== "object") return []
    const { keyword, volume } = item as Record<string, unknown>
    if (typeof keyword !== "string" || !keyword) return []
    if (typeof volume !== "number" || !Number.isFinite(volume)) return []
    return [{ keyword, volume }]
  })
}

// Zoekwoordposities uit Pro Rank Tracker. Faalt nooit hard: zonder autorisatie,
// bij een HTTP-fout of een onverwacht antwoord komt er `state: "error"` terug.
export async function fetchCustomerRankings(
  customerId: string
): Promise<CustomerRankings> {
  noStore()

  const authorization = await getBackendAuthorizationValue()
  if (!authorization) {
    return emptyRankings()
  }

  try {
    const response = await fetch(
      `${getBackendApiUrl()}/api/customers/${encodeURIComponent(customerId)}/rankings`,
      {
        method: "GET",
        headers: {
          Authorization: authorization,
        },
        cache: "no-store",
      }
    )

    if (!response.ok) {
      return emptyRankings()
    }

    const payload = (await response.json().catch(() => null)) as Record<
      string,
      unknown
    > | null
    const state = payload?.state
    if (
      !payload ||
      typeof state !== "string" ||
      !RANKING_STATES.includes(state as CustomerRankingsState)
    ) {
      return emptyRankings()
    }

    const contentGaps = parseContentGaps(payload.content_gaps)
    return {
      state: state as CustomerRankingsState,
      message: stringOrNull(payload.message),
      fetched_at: stringOrNull(payload.fetched_at),
      keywords: numberOr(payload.keywords, 0),
      ranked: numberOr(payload.ranked, 0),
      avg_position: numberOr(payload.avg_position, null),
      avg_position_delta: numberOr(payload.avg_position_delta, null),
      top3: numberOr(payload.top3, 0),
      top3_delta: numberOr(payload.top3_delta, null),
      content_gaps: contentGaps,
      // Ontbreekt het totaal (oudere backend), dan is het minstens het getoonde aantal.
      content_gaps_total: Math.max(
        numberOr(payload.content_gaps_total, 0),
        contentGaps.length
      ),
    }
  } catch {
    return emptyRankings()
  }
}

const QUICK_WINS_STATES: CustomerQuickWinsState[] = ["ok", "not_configured", "error"]
const QUICK_WIN_CHANCES: QuickWinChance[] = ["hoog", "middel", "laag"]
const QUICK_WIN_SOURCES: QuickWinSource[] = ["prt", "ahrefs", "both"]
const DEFAULT_QUICK_WINS_LIMIT = 50

function emptyQuickWins(): CustomerQuickWins {
  return {
    state: "error",
    message: null,
    fetched_at: null,
    limit: DEFAULT_QUICK_WINS_LIMIT,
    capped: false,
    rows: [],
  }
}

function parseQuickWinRow(value: unknown): CustomerQuickWinRow | null {
  if (!value || typeof value !== "object") return null
  const row = value as Record<string, unknown>
  const position = numberOr(row.position, null)
  if (typeof row.keyword !== "string" || !row.keyword || position === null) return null
  const kans = QUICK_WIN_CHANCES.includes(row.kans as QuickWinChance)
    ? (row.kans as QuickWinChance)
    : "middel"
  return {
    keyword: row.keyword,
    position,
    delta: numberOr(row.delta, null),
    volume: numberOr(row.volume, null),
    kd: numberOr(row.kd, null),
    url: stringOrNull(row.url),
    kans,
    // Een antwoord zonder `source` komt van de oude backend, die alleen Ahrefs kende.
    source: QUICK_WIN_SOURCES.includes(row.source as QuickWinSource)
      ? (row.source as QuickWinSource)
      : "ahrefs",
  }
}

// Quick wins (positie 4–20) uit de bewaarde Ahrefs-stand. Faalt nooit hard: zonder
// autorisatie, bij een HTTP-fout of een onverwacht antwoord komt er `state: "error"` terug.
export async function fetchCustomerQuickWins(
  customerId: string
): Promise<CustomerQuickWins> {
  noStore()

  const authorization = await getBackendAuthorizationValue()
  if (!authorization) {
    return emptyQuickWins()
  }

  try {
    const response = await fetch(
      `${getBackendApiUrl()}/api/customers/${encodeURIComponent(customerId)}/quick-wins`,
      {
        method: "GET",
        headers: {
          Authorization: authorization,
        },
        cache: "no-store",
      }
    )

    if (!response.ok) {
      return emptyQuickWins()
    }

    const payload = (await response.json().catch(() => null)) as Record<
      string,
      unknown
    > | null
    const state = payload?.state
    if (
      !payload ||
      typeof state !== "string" ||
      !QUICK_WINS_STATES.includes(state as CustomerQuickWinsState)
    ) {
      return emptyQuickWins()
    }

    const rows = Array.isArray(payload.rows)
      ? payload.rows
          .map(parseQuickWinRow)
          .filter((row): row is CustomerQuickWinRow => row !== null)
      : []
    const limit = numberOr(payload.limit, DEFAULT_QUICK_WINS_LIMIT)

    return {
      state: state as CustomerQuickWinsState,
      message: stringOrNull(payload.message),
      fetched_at: stringOrNull(payload.fetched_at),
      limit: limit > 0 ? limit : DEFAULT_QUICK_WINS_LIMIT,
      capped: payload.capped === true,
      rows,
    }
  } catch {
    return emptyQuickWins()
  }
}

// Open verbeterpunten uit het scherm Aanpassingen. Geeft `null` bij geen
// autorisatie, een HTTP-fout of een onverwacht antwoord.
export async function fetchCustomerImprovements(
  customerId: string
): Promise<CustomerImprovements | null> {
  noStore()

  const authorization = await getBackendAuthorizationValue()
  if (!authorization) {
    return null
  }

  try {
    const response = await fetch(
      `${getBackendApiUrl()}/api/site-changes/customers/${encodeURIComponent(customerId)}/pages`,
      {
        method: "GET",
        headers: {
          Authorization: authorization,
        },
        cache: "no-store",
      }
    )

    if (!response.ok) {
      return null
    }

    const payload = (await response.json().catch(() => null)) as {
      totals?: { open?: unknown; open_high?: unknown } | null
      has_sources?: unknown
    } | null
    const open = numberOr(payload?.totals?.open, null)
    if (open === null) {
      return null
    }

    return {
      open,
      // `open_high` ontbreekt zolang de backend het nog niet levert.
      openHigh: numberOr(payload?.totals?.open_high, 0),
      hasSources: payload?.has_sources !== false,
    }
  } catch {
    return null
  }
}
