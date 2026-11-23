/**
 * Aanpassingen per pagina: voorstellen en actiepunten van een klantsite beoordelen,
 * afvinken en laten controleren op de live pagina. Alles loopt via de proxy
 * onder `/api/site-changes`.
 */

export type Topic =
  | "meta_title"
  | "meta_description"
  | "headings"
  | "text"
  | "faq"
  | "image_alt"
  | "internal_links"
  | "technical"
  | "performance"
  | "other"

export type ChangeStatus = "open" | "goedgekeurd" | "afgewezen" | "doorgevoerd"
export type ChangeSourceKind = "content_suggestion" | "scan_issue"
export type ChangeAction = "approve" | "reject" | "reopen" | "done"

export type ChangeSourceRef = { suggestion_id?: string; issue_id?: string }

export type VerifyDetail = {
  checked_at: string
  message: string | null
  live_value: string | null
  missing: string[]
}

export type ChangeItem = {
  key: string
  change_id: string | null
  source_kind: ChangeSourceKind
  source_ref: ChangeSourceRef
  topic: Topic
  title: string
  description: string | null
  current_value: string | null
  /** null bij actiepunten. */
  proposed_value: string | null
  approved_value: string | null
  edited: boolean
  /** Voorstel: waarom; actiepunt: aanpak. */
  rationale: string | null
  ref: string | null
  severity: "laag" | "middel" | "hoog" | null
  item_label: string | null
  status: ChangeStatus
  checkable: boolean
  /** true = live teruggezien, false = gecontroleerd maar niet gevonden, null = niet gecontroleerd. */
  verified: boolean | null
  verify_detail: VerifyDetail | null
  /** Weergavenaam. */
  reviewed_by: string | null
  reviewed_at: string | null
  done_by: string | null
  done_at: string | null
  note: string | null
}

export type PageSummary = {
  url: string
  path: string
  title: string | null
  open_count: number
  approved_count: number
  done_count: number
}

export type PagesResponse = {
  pages: PageSummary[]
  totals: { open: number; approved: number; done: number }
  has_sources: boolean
}

export type SchemaSummary = {
  status: "none" | "suggested" | "approved" | "rejected" | "placed"
  types: string[]
  placed_at: string | null
  verified: boolean | null
}

export type ChangeGroup = { topic: Topic; label: string; items: ChangeItem[] }

export type PageDetail = {
  url: string
  path: string
  title: string | null
  /** Status open + goedgekeurd. */
  groups: ChangeGroup[]
  rejected: ChangeItem[]
  /** Nieuwste eerst. */
  done: ChangeItem[]
  schema: SchemaSummary | null
  last_checked_at: string | null
}

export type PageCheckResponse = {
  page: PageDetail
  checked: number
  verified: number
  resolved_issues: number
}

export const TOPIC_LABELS: Record<Topic, string> = {
  meta_title: "Meta title",
  meta_description: "Meta description",
  headings: "Koppen",
  text: "Tekst",
  faq: "FAQ",
  image_alt: "Alt-teksten",
  internal_links: "Interne links",
  technical: "Techniek",
  performance: "Performance",
  other: "Overig",
}

export const SCHEMA_STATUS_LABELS: Record<SchemaSummary["status"], string> = {
  none: "Geen voorstel",
  suggested: "Voorstel klaar",
  approved: "Goedgekeurd",
  rejected: "Afgewezen",
  placed: "Geplaatst",
}

export const API_BASE = "/api/site-changes"

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { cache: "no-store", ...init })
  const payload = (await response.json().catch(() => null)) as (T & { error?: string }) | null
  if (!response.ok) {
    throw new Error(payload?.error?.trim() || "Er ging iets mis.")
  }
  return payload as T
}

/** Fout met de HTTP-status, zodat een 404 ("geen punten op deze URL") apart te tonen is. */
export class SiteChangesError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
  }
}

export function fetchPages(customerId: string) {
  return apiFetch<PagesResponse>(`/customers/${encodeURIComponent(customerId)}/pages`)
}

export async function fetchPageDetail(customerId: string, url: string): Promise<PageDetail> {
  const response = await fetch(
    `${API_BASE}/customers/${encodeURIComponent(customerId)}/page?url=${encodeURIComponent(url)}`,
    { cache: "no-store" }
  )
  const payload = (await response.json().catch(() => null)) as (PageDetail & { error?: string }) | null
  if (!response.ok) {
    throw new SiteChangesError(payload?.error?.trim() || "Er ging iets mis.", response.status)
  }
  return payload as PageDetail
}

export function updateChange(
  customerId: string,
  item: ChangeItem,
  action: ChangeAction,
  extra: { value?: string; note?: string } = {}
) {
  return apiFetch<ChangeItem>(`/customers/${encodeURIComponent(customerId)}/changes`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      key: item.key,
      source_kind: item.source_kind,
      source_ref: item.source_ref,
      action,
      ...extra,
    }),
  })
}

export function checkPage(customerId: string, url: string) {
  return apiFetch<PageCheckResponse>(`/customers/${encodeURIComponent(customerId)}/page/check`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  })
}

/** Link naar het scherm Aanpassingen, eventueel direct op één pagina. */
export function changesHref(customerId: string, url?: string | null) {
  const params = new URLSearchParams({ fase: "aanpassingen" })
  if (url) params.set("url", url)
  return `/dashboard/livegang/seo-geo/${customerId}?${params}`
}
