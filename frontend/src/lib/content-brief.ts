/**
 * Content brief en concepttekst per zoekwoord uit een concurrentieanalyse: types, API-aanroepen
 * en het adres van het scherm. Loopt via dezelfde proxy als de analyse (`/api/competitor-analyses`).
 *
 * De types volgen het contract met `backend/app/features/competitor_analysis` (zelfde veldnamen).
 * Kosten in USD (`AiUsage.cost_usd`); tijdstippen zijn ISO-tekst.
 */

import {
  KEYWORD_PARAM,
  analysisHref,
  apiFetch,
  type AiUsage,
} from "@/lib/competitor-analysis"

// --- Types ----------------------------------------------------------------------------------

/** `pending` = in de wachtrij, `brief`/`concept` = die stap loopt. */
export type ContentBriefStatus = "pending" | "brief" | "concept" | "completed" | "failed"

export const ACTIVE_BRIEF_STATUSES: readonly ContentBriefStatus[] = ["pending", "brief", "concept"]

export type HeadingLevel = "h1" | "h2" | "h3"

export type FormOfAddress = "je" | "u"

export type OutlineItem = {
  level: HeadingLevel
  text: string
}

export type Brief = {
  /** 2–4 bullets. */
  goal_intent: string[]
  title: string
  meta_description: string
  outline: OutlineItem[]
  /** Richtlengte in woorden. */
  word_count: number
  /** Uit het klantprofiel; null = niet ingevuld. */
  tone_of_voice: string | null
  form_of_address: FormOfAddress | null
  /** Paden op de site van de klant. */
  internal_links: string[]
  schema_types: string[]
}

export type ConceptSection = {
  level: HeadingLevel
  heading: string
  /** Markdown. */
  body: string
  /** Wat de reviewer moet controleren; null = niets. */
  review_note: string | null
}

export type ConceptCheckKey = "topics" | "questions" | "keyword" | "length" | "review"

export type ConceptCheck = {
  key: ConceptCheckKey
  label: string
  ok: boolean
}

export type Concept = {
  version: number
  /** Door de backend geteld. */
  word_count: number
  sections: ConceptSection[]
  checks: ConceptCheck[]
}

/** Antwoord van alle drie de endpoints. */
export type ContentBrief = {
  id: string
  analysis_id: string
  keyword_id: string
  keyword: string
  target_url: string | null
  status: ContentBriefStatus
  error_message: string | null
  analysis_date: string | null
  model: string | null
  ai_usage: AiUsage | null
  created_at: string
  updated_at: string
  completed_at: string | null
  brief: Brief | null
  concept: Concept | null
}

/** Eén rij in het overzicht van content briefs van een klant. */
export type ContentBriefListItem = {
  id: string
  analysis_id: string
  keyword_id: string
  keyword: string
  target_url: string | null
  status: ContentBriefStatus
  error_message: string | null
  /** Title uit de brief; null zolang de brief er niet is. */
  title: string | null
  concept_version: number | null
  /** Woorden van de concepttekst; null zolang die er niet is. */
  word_count: number | null
  analysis_date: string | null
  created_at: string
  updated_at: string
  completed_at: string | null
}

export type ContentBriefListResponse = {
  items: ContentBriefListItem[]
}

export const BRIEF_STATUS_LABELS: Record<ContentBriefStatus, string> = {
  pending: "In de wachtrij",
  brief: "Brief wordt opgesteld",
  concept: "Tekst wordt geschreven",
  completed: "Concept klaar",
  failed: "Mislukt",
}

// --- Hulpfuncties ---------------------------------------------------------------------------

export function isBriefActive(status: ContentBriefStatus) {
  return ACTIVE_BRIEF_STATUSES.includes(status)
}

/** Het scherm met brief en concept voor één zoekwoord. */
export function briefHref(customerId: string, analysisId: string, keywordId: string) {
  return `${analysisHref(customerId, analysisId)}/brief?${new URLSearchParams({ [KEYWORD_PARAM]: keywordId })}`
}

/** Modelnaam leesbaar: "claude-sonnet-5-5" → "Claude Sonnet 5.5"; null → "Claude". */
export function modelLabel(model: string | null | undefined) {
  if (!model?.trim()) return "Claude"
  const parts = model.trim().split("-")
  const words: string[] = []
  const version: string[] = []
  for (const part of parts) {
    if (/^\d+$/.test(part) && part.length <= 2) version.push(part)
    else if (version.length === 0 && !/^\d{6,}$/.test(part)) words.push(part.charAt(0).toUpperCase() + part.slice(1))
  }
  return [...words, version.join(".")].filter(Boolean).join(" ")
}

// --- API ------------------------------------------------------------------------------------

const briefPath = (analysisId: string, keywordId: string) =>
  `/analyses/${encodeURIComponent(analysisId)}/keywords/${encodeURIComponent(keywordId)}/brief`

/** Content briefs van een klant, laatst bijgewerkte eerst. */
export function fetchBriefs(customerId: string, limit?: number) {
  const query = limit ? `?${new URLSearchParams({ limit: String(limit) })}` : ""
  return apiFetch<ContentBriefListResponse>(`/customers/${encodeURIComponent(customerId)}/briefs${query}`)
}

/** De brief van een zoekwoord; 404 als er nog geen is. */
export function fetchBrief(analysisId: string, keywordId: string) {
  return apiFetch<ContentBrief>(briefPath(analysisId, keywordId))
}

/**
 * Start de brief (of herstart na `failed`; de backend hervat vanaf de mislukte stap).
 * 400 als het zoekwoord niet klaar is, 409 als er al een loopt of klaar is, 503 zonder wachtrij of sleutel.
 */
export function startBrief(analysisId: string, keywordId: string) {
  return apiFetch<ContentBrief>(briefPath(analysisId, keywordId), { method: "POST" })
}

/** Alleen de concepttekst opnieuw schrijven; 409 als er geen brief is of er een run loopt. */
export function regenerateConcept(analysisId: string, keywordId: string) {
  return apiFetch<ContentBrief>(`${briefPath(analysisId, keywordId)}/concept`, { method: "POST" })
}
