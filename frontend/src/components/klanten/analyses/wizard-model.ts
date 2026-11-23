// Rijen, voorvullen en controle van de wizard "Nieuwe analyse". Pure functies, zodat de
// componenten alleen tonen. De controles volgen de router van de backend
// (`competitor_analysis/router.py`: maximum, dubbele zoekwoorden, doel-URL op het klantdomein).

import type { KeywordInput, Module, ProposalKeyword } from "@/lib/competitor-analysis"

/** Keuze "+ Nieuwe pagina (nog geen ranking)": stuurt `target_url: null`. */
export const NEW_PAGE = "__new__"
/** Keuze "Andere URL…": toont een tekstveld. */
export const CUSTOM_URL = "__custom__"

/** Zelfde grens als `KeywordInput.keyword` in de backend. */
export const MAX_KEYWORD_LENGTH = 200

export type WizardRow = {
  id: string
  keyword: string
  /** Een URL uit het voorstel, `NEW_PAGE` of `CUSTOM_URL`. */
  target: string
  /** Tekst van het veld "Andere URL…". */
  customUrl: string
  /** Sleutel van het bekende zoekwoord waarvoor de doelpagina het laatst is voorgevuld. */
  filledFor: string | null
  /** De gebruiker koos zelf een doelpagina; een onbekend zoekwoord zet hem dan niet terug. */
  targetTouched: boolean
}

export type RowErrors = { keyword?: string; url?: string }

let rowCounter = 0
function newRowId() {
  rowCounter += 1
  return `rij-${rowCounter}`
}

/** Zoekwoord zoals de backend het opslaat: witruimte samengevoegd en getrimd. */
export function cleanKeyword(value: string) {
  return value.split(/\s+/).filter(Boolean).join(" ")
}

/** "Hetzelfde zoekwoord" zoals `keyword_key` in de backend. */
export function keywordKey(value: string) {
  return cleanKeyword(value).toLowerCase()
}

export function knownByKey(keywords: ProposalKeyword[]) {
  const map = new Map<string, ProposalKeyword>()
  for (const item of keywords) {
    const key = keywordKey(item.keyword)
    if (key && !map.has(key)) map.set(key, item)
  }
  return map
}

/** Doelpagina voor een (on)bekend zoekwoord: de rankende URL, anders een nieuwe pagina. */
function prefilledTarget(known: ProposalKeyword | undefined) {
  return known?.url ? known.url : NEW_PAGE
}

export function createRow(keyword: string, known: Map<string, ProposalKeyword>): WizardRow {
  const key = keywordKey(keyword)
  const match = key ? known.get(key) : undefined
  return {
    id: newRowId(),
    keyword,
    target: prefilledTarget(match),
    customUrl: "",
    filledFor: match ? key : null,
    targetTouched: false,
  }
}

/**
 * Nieuw zoekwoord in een rij. Een bekend zoekwoord vult doelpagina en (afgeleid) positie voor;
 * een onbekend zoekwoord zet de doelpagina terug op "Nieuwe pagina", tenzij de gebruiker die
 * zelf koos.
 */
export function withKeyword(row: WizardRow, keyword: string, known: Map<string, ProposalKeyword>): WizardRow {
  const key = keywordKey(keyword)
  const match = key ? known.get(key) : undefined
  if (match) {
    if (row.filledFor === key) return { ...row, keyword }
    return { ...row, keyword, target: prefilledTarget(match), customUrl: "", filledFor: key, targetTouched: false }
  }
  if (row.targetTouched) return { ...row, keyword, filledFor: null }
  return { ...row, keyword, target: NEW_PAGE, customUrl: "", filledFor: null }
}

// --- URL's ------------------------------------------------------------------------------------

/** Host zonder `www.` (kleine letters), ook voor een adres zonder schema; leeg als ongeldig. */
export function hostOf(value: string | null | undefined) {
  const text = (value ?? "").trim()
  if (!text) return ""
  try {
    const url = new URL(text.includes("://") ? text : `http://${text}`)
    return url.hostname.toLowerCase().replace(/^www\./, "")
  } catch {
    return ""
  }
}

/** Zelfde host of een subdomein ervan, zoals `on_domain` in de backend. */
export function isOnDomain(url: string, host: string) {
  if (!host) return false
  const urlHost = hostOf(url)
  return !!urlHost && (urlHost === host || urlHost.endsWith(`.${host}`))
}

/**
 * Absolute http(s)-URL uit het veld "Andere URL…". Een pad ("/diensten/seo") komt op de site
 * van de klant; zonder schema krijgt het adres `https://`. `null` als het geen webadres is.
 */
export function resolveUrl(raw: string, baseUrl: string): string | null {
  const text = raw.trim()
  if (!text) return null
  try {
    let url: URL
    if (text.startsWith("/")) {
      if (!baseUrl) return null
      url = new URL(text, baseUrl.includes("://") ? baseUrl : `https://${baseUrl}`)
    } else {
      url = new URL(text.includes("://") ? text : `https://${text}`)
    }
    if ((url.protocol !== "http:" && url.protocol !== "https:") || !url.hostname) return null
    return url.href
  } catch {
    return null
  }
}

/** Korte weergave "iexist.nl/seo": host zonder `www.` plus pad, zonder afsluitende slash. */
export function shortUrl(url: string) {
  try {
    const parsed = new URL(url)
    const path = `${parsed.pathname}${parsed.search}`.replace(/\/$/, "")
    return `${parsed.hostname.replace(/^www\./, "")}${path}`
  } catch {
    return url
  }
}

/** De gekozen doel-URL van een rij; `null` = nieuwe pagina (of een ongeldige eigen URL). */
export function rowTargetUrl(row: WizardRow, baseUrl: string): string | null {
  if (row.target === NEW_PAGE) return null
  if (row.target === CUSTOM_URL) return resolveUrl(row.customUrl, baseUrl)
  return row.target
}

// --- Controle ---------------------------------------------------------------------------------

export type Validation = {
  rows: Record<string, RowErrors>
  /** Meldingen voor het formulier als geheel (bij de zoekwoordenkaart). */
  keywords: string | null
  modules: string | null
  valid: boolean
}

export function validate({
  rows,
  modules,
  maxKeywords,
  host,
  baseUrl,
}: {
  rows: WizardRow[]
  modules: readonly Module[]
  maxKeywords: number
  host: string
  baseUrl: string
}): Validation {
  const errors: Record<string, RowErrors> = {}
  const seen = new Set<string>()
  const filled = rows.filter((row) => keywordKey(row.keyword)).length

  for (const row of rows) {
    const rowErrors: RowErrors = {}
    const keyword = cleanKeyword(row.keyword)
    const key = keyword.toLowerCase()
    if (!key) {
      rowErrors.keyword = filled === 0 ? "Vul minstens één zoekwoord in." : "Vul een zoekwoord in of verwijder deze rij."
    } else if (keyword.length > MAX_KEYWORD_LENGTH) {
      rowErrors.keyword = `Maximaal ${MAX_KEYWORD_LENGTH} tekens.`
    } else if (seen.has(key)) {
      rowErrors.keyword = "Dit zoekwoord staat er al in."
    }
    if (key) seen.add(key)

    if (row.target === CUSTOM_URL) {
      const url = resolveUrl(row.customUrl, baseUrl)
      if (!row.customUrl.trim()) rowErrors.url = "Vul een URL in, of kies een pagina uit de lijst."
      else if (!url) rowErrors.url = "Dit is geen geldig webadres."
      else if (!isOnDomain(url, host)) rowErrors.url = `De doelpagina moet op ${host || "het domein van de klant"} liggen.`
    }

    if (rowErrors.keyword || rowErrors.url) errors[row.id] = rowErrors
  }

  const keywords =
    rows.length > maxKeywords
      ? `Kies maximaal ${maxKeywords} zoekwoorden per analyse (nu ${rows.length}).`
      : null
  const modulesError = modules.length === 0 ? "Kies minstens één onderdeel om te analyseren." : null

  return {
    rows: errors,
    keywords,
    modules: modulesError,
    valid: Object.keys(errors).length === 0 && !keywords && !modulesError,
  }
}

/** Duplicaten tonen we meteen; de overige meldingen pas na een poging om te starten. */
export function isLiveError(message: string | undefined) {
  return message === "Dit zoekwoord staat er al in."
}

export function toKeywordInputs(rows: WizardRow[], baseUrl: string): KeywordInput[] {
  return rows.map((row) => ({ keyword: cleanKeyword(row.keyword), target_url: rowTargetUrl(row, baseUrl) }))
}

// --- Notatie ----------------------------------------------------------------------------------

const numberFormat = new Intl.NumberFormat("nl-NL")
const euroFormat = new Intl.NumberFormat("nl-NL", {
  style: "currency",
  currency: "EUR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

export function formatNumber(value: number) {
  return numberFormat.format(value)
}

export function formatEuro(value: number) {
  return euroFormat.format(value)
}
