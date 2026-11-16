"use client"

import { ExternalLink } from "lucide-react"
import { useState } from "react"

import { HttpStatusBadge, Pill } from "@/components/livegang/shared"
import { CWV_LABELS } from "@/lib/launch-checklist"

/**
 * Generieke weergave van `issue.details` voor actiepunten zonder eigen renderer.
 *
 * Kijkt naar de vorm van de gegevens, niet naar het type actiepunt: losse waarden
 * worden label–waarde-rijen, lijsten met URL's worden links, lijsten met kleine
 * objecten een compacte tabel. Nooit ruwe JSON.
 */

/** Interne boekhouding die voor de gebruiker niets betekent (de waarde-boost staat al als label bij het actiepunt). */
const HIDDEN_KEYS = new Set(["value_boost"])

/** Zoveel regels per lijst tonen; de rest achter "en nog N". */
const LIST_LIMIT = 10

/** Langere tekst (of tekst met regeleinden) krijgt een eigen blok in plaats van een rij. */
const LONG_TEXT = 120

const LABELS: Record<string, string> = {
  // fase 1: pagina-issues
  status: "Statuscode",
  status_code: "Statuscode",
  http_code: "Statuscode",
  final_status: "Eindstatus",
  refdomains: "Verwijzende domeinen",
  org_traffic: "Organische bezoeken/maand",
  backlinks: "Backlinks naar deze pagina",
  url_from: "Linkt vanaf",
  dr: "DR",
  anchor: "Ankertekst",
  chain: "Redirectketen",
  location: "Verwijst naar",
  final: "Eindbestemming",
  canonical: "Canonical",
  title: "Title",
  meta_description: "Meta description",
  length: "Lengte",
  pixels: "Breedte",
  h1: "H1-koppen",
  word_count: "Aantal woorden",
  measure: "Geteld in",
  missing: "Ontbreekt",
  total: "Totaal",
  value: "Waarde",
  duplicates: "Komt ook voor op",
  links: "Links",
  ttfb_ms: "Server-responstijd (TTFB)",
  response_time_ms: "Responstijd",
  source: "Bron",
  urls: "Pagina's",
  url: "URL",
  rating: "Beoordeling",
  metric: "Meetwaarde",
  // AI-vindbaarheid
  blocked: "Geblokkeerde bots",
  sitemaps: "Sitemaps",
  preview: "Voorbeeld",
  coverage: "Dekking",
  types: "Schematypes",
  fetched: "Bestand opgehaald",
  bots: "Bots",
  bot: "Bot",
  allowed: "Toegestaan",
  search_bot: "Zoekbot",
  // fase 2 en 3
  evidence: "Bevindingen",
  pages: "Pagina's",
  with_schema: "Met schema",
  with_problems: "Met verbeterpunten",
  analysed: "Geanalyseerd",
  with_suggestions: "Met open voorstellen",
  suggestions: "Open voorstellen",
  child_sitemaps: "Sub-sitemaps",
  found: "Gevonden",
  linked: "Gelinkt vanaf de site",
  content_images: "Eigen afbeeldingen",
  reviews: "Reviews of klantuitspraken",
  author: "Auteur",
  content_inlinks: "Links vanuit lopende tekst",
  links_without_text: "Links zonder tekst",
  generic: "Nietszeggende linkteksten",
  text: "Linktekst",
  place: "Plaats",
  mentions: "Vermeldingen",
  region_words: "Regiowoorden",
  images: "Afbeeldingen",
  src: "Bron-URL",
  alt: "Alt-tekst",
  filename: "Bestandsnaam",
  missing_alt: "Geen alt",
  generic_filename: "Nietszeggende bestandsnaam",
  broken: "Kapot",
  redirects: "Redirects",
  // meertaligheid, robots, social en paginagewicht (fase 1)
  lang: "Taal",
  href: "Href",
  problem: "Probleem",
  problems: "Problemen",
  targets: "Doelpagina's",
  reason: "Reden",
  blocked_for: "Geblokkeerd voor",
  rule: "Regel",
  relative_image: "Relatieve afbeeldings-URL's",
  bytes: "Grootte",
  data: "Gegevens",
}

/** Vertaalde waarden voor sleutels met een vaste set waarden. */
const VALUE_LABELS: Record<string, Record<string, string>> = {
  source: {
    pagespeed: "Google PageSpeed",
    scan: "Eigen scan",
    ai: "AI-analyse",
    veld: "Velddata (Chrome-gebruikers)",
    lab: "Labdata (Lighthouse)",
  },
  rating: CWV_LABELS,
  // weinig content (fase 1)
  measure: {
    main: "Hoofdinhoud (zonder menu, kop, voet en zijbalk)",
    total: "Alle tekst in de HTML",
  },
}

const STATUS_KEYS = new Set(["status", "status_code", "http_code", "final_status"])

const linkClass = "inline-flex min-w-0 max-w-full items-center gap-1 break-all text-primary hover:underline"

type Entry = [key: string, value: unknown]

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function isScalar(value: unknown): value is string | number | boolean {
  return typeof value === "string" || typeof value === "number" || typeof value === "boolean"
}

function isEmpty(value: unknown) {
  return (
    value === null ||
    value === undefined ||
    value === "" ||
    (Array.isArray(value) && value.length === 0) ||
    (isPlainObject(value) && Object.keys(value).length === 0)
  )
}

function isUrl(value: unknown): boolean {
  return typeof value === "string" && /^https?:\/\/\S+$/i.test(value.trim())
}

function isLongText(value: unknown) {
  return typeof value === "string" && !isUrl(value) && (value.length > LONG_TEXT || value.includes("\n"))
}

/** "relative_image" → "Relative image" voor sleutels zonder Nederlandse vertaling. */
function humanize(key: string) {
  const text = key.replace(/[_-]+/g, " ").trim()
  return text ? text[0].toUpperCase() + text.slice(1) : key
}

function labelOf(key: string) {
  return LABELS[key] ?? humanize(key)
}

const numberFormat = (value: number, digits = 2) => value.toLocaleString("nl-NL", { maximumFractionDigits: digits })

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${numberFormat(bytes, 0)} B`
  if (bytes < 1024 * 1024) return `${numberFormat(bytes / 1024, 1)} kB`
  return `${numberFormat(bytes / (1024 * 1024), 1)} MB`
}

function formatNumberFor(key: string, value: number) {
  if (key.endsWith("_ms")) return `${numberFormat(Math.round(value), 0)} ms`
  if (key.endsWith("_pct") || key === "coverage") return `${numberFormat(value, 1)}%`
  if (key === "bytes") return formatBytes(value)
  if (key === "length") return `${numberFormat(value, 0)} tekens`
  if (key === "pixels") return `${numberFormat(value, 0)} px`
  return numberFormat(value)
}

function PageLink({ url }: { url: string }) {
  return (
    <a href={url} target="_blank" rel="noreferrer noopener" className={linkClass}>
      <span className="break-all">{url}</span>
      <ExternalLink className="size-3 shrink-0" />
    </a>
  )
}

/** Eén losse waarde, opgemaakt naar de sleutel waar hij onder staat. */
function ScalarValue({ name, value }: { name: string; value: unknown }) {
  if (value === null || value === undefined || value === "") return <span className="text-muted-foreground">—</span>
  if (typeof value === "boolean") return <>{value ? "Ja" : "Nee"}</>
  if (typeof value === "number") {
    if (STATUS_KEYS.has(name)) return <HttpStatusBadge status={value} />
    return <span className="tabular-nums">{formatNumberFor(name, value)}</span>
  }
  if (typeof value === "string") {
    if (isUrl(value)) return <PageLink url={value} />
    const translated = VALUE_LABELS[name]?.[value]
    if (translated) return <>{translated}</>
    if (name === "rule" || name === "href") {
      return <code className="break-all rounded bg-muted px-1.5 py-0.5 font-mono text-[11px]">{value}</code>
    }
    return <span className="break-words">{value}</span>
  }
  if (Array.isArray(value)) {
    // In een tabelcel: kort samenvatten (bv. Bing-meldingen met een label).
    return <span className="break-words">{value.map((v) => inlineText(v)).join(", ")}</span>
  }
  return <span className="break-words">{inlineText(value)}</span>
}

/** Platte tekst voor geneste waarden in een cel of lijstregel. */
function inlineText(value: unknown): string {
  if (value === null || value === undefined) return "—"
  if (typeof value === "boolean") return value ? "ja" : "nee"
  if (isScalar(value)) return String(value)
  if (Array.isArray(value)) return value.map(inlineText).join(", ")
  if (isPlainObject(value)) {
    if (typeof value.label === "string") return value.label
    return Object.entries(value)
      .filter(([k, v]) => !HIDDEN_KEYS.has(k) && !isEmpty(v))
      .map(([k, v]) => `${LABELS[k] ?? k}: ${inlineText(v)}`)
      .join(" · ")
  }
  return String(value)
}

/**
 * Sleutels uit `details` in weergavevolgorde. `data` (fase 2/3) wordt uitgepakt,
 * lege en interne sleutels vallen weg, en `<lijst>_total` gaat als totaal naar die lijst.
 */
function collectEntries(details: Record<string, unknown>) {
  const entries: Entry[] = []
  for (const [key, value] of Object.entries(details)) {
    if (HIDDEN_KEYS.has(key) || isEmpty(value)) continue
    if (key === "data" && isPlainObject(value)) {
      for (const [innerKey, innerValue] of Object.entries(value)) {
        if (HIDDEN_KEYS.has(innerKey) || isEmpty(innerValue)) continue
        if (!entries.some(([k]) => k === innerKey)) entries.push([innerKey, innerValue])
      }
    } else {
      entries.push([key, value])
    }
  }
  const totals: Record<string, number> = {}
  const listKeys = new Set(entries.filter(([, v]) => Array.isArray(v)).map(([k]) => k))
  const visible = entries.filter(([key, value]) => {
    const list = key.endsWith("_total") ? key.slice(0, -"_total".length) : null
    if (list && listKeys.has(list) && typeof value === "number") {
      totals[list] = value
      return false
    }
    return true
  })
  return { entries: visible, totals }
}

export function IssueDetails({ details, className }: { details: unknown; className?: string }) {
  if (isEmpty(details)) return null
  const root: Record<string, unknown> = isPlainObject(details) ? details : { [Array.isArray(details) ? "data" : "value"]: details }
  const { entries, totals } = collectEntries(root)
  if (!entries.length) return null
  return (
    <div className={className}>
      <Fields entries={entries} totals={totals} depth={0} />
    </div>
  )
}

/** Losse waarden als label–waarde-rijen, daaronder lijsten en geneste blokken met een kopje. */
function Fields({ entries, totals = {}, depth, verbatimKeys = false }: {
  entries: Entry[]
  totals?: Record<string, number>
  depth: number
  /** Sleutels zijn zelf gegevens (bv. schematypes of og-tags): niet vertalen of opmaken. */
  verbatimKeys?: boolean
}) {
  const label = (key: string) => (verbatimKeys ? (LABELS[key] ?? key) : labelOf(key))
  const rows = entries.filter(([, value]) => isScalar(value) && !isLongText(value))
  const blocks = entries.filter(([, value]) => !isScalar(value) || isLongText(value))
  return (
    <div className="space-y-3 text-xs">
      {rows.length > 0 && (
        <dl className="grid grid-cols-[minmax(0,max-content)_minmax(0,1fr)] gap-x-4 gap-y-1 rounded-md border bg-card px-3 py-2">
          {rows.map(([key, value]) => (
            <div key={key} className="contents">
              <dt className="text-muted-foreground">{label(key)}</dt>
              <dd className="min-w-0">
                <ScalarValue name={key} value={value} />
              </dd>
            </div>
          ))}
        </dl>
      )}
      {blocks.map(([key, value]) => (
        <Block key={key} title={label(key)} name={key} value={value} total={totals[key]} depth={depth} />
      ))}
    </div>
  )
}

function Block({ title, name, value, total, depth }: {
  title: string
  name: string
  value: unknown
  total?: number
  depth: number
}) {
  const count = Array.isArray(value) ? (total ?? value.length) : null
  return (
    <div className="min-w-0">
      <p className="mb-1 text-xs font-medium text-muted-foreground">
        {title}
        {count !== null && ` (${count})`}
      </p>
      <BlockContent name={name} value={value} total={total} depth={depth} />
    </div>
  )
}

function BlockContent({ name, value, total, depth }: { name: string; value: unknown; total?: number; depth: number }) {
  if (typeof value === "string") {
    return (
      <p className="max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-md border bg-card px-3 py-2 font-mono text-[11px]">
        {value}
      </p>
    )
  }
  if (Array.isArray(value)) return <ListValue name={name} items={value} total={total} />
  if (isPlainObject(value)) {
    const entries = Object.entries(value).filter(([k, v]) => !HIDDEN_KEYS.has(k) && !isEmpty(v))
    if (depth >= 2) return <p className="break-words text-muted-foreground">{inlineText(value)}</p>
    // Objecten met alleen losse waarden zijn meestal tellingen per sleutel (schematypes, ontbrekende og-tags).
    const verbatim = entries.every(([, v]) => isScalar(v))
    return <Fields entries={entries} depth={depth + 1} verbatimKeys={verbatim} />
  }
  return <ScalarValue name={name} value={value} />
}

/** Lijst: links, labels, tekstregels, een redirectketen of een tabel, afhankelijk van de inhoud. */
function ListValue({ name, items, total }: { name: string; items: unknown[]; total?: number }) {
  const [expanded, setExpanded] = useState(false)
  const shown = expanded ? items : items.slice(0, LIST_LIMIT)
  const hiddenHere = items.length - shown.length
  // Lijsten die de backend al heeft ingekort, met het echte totaal ernaast.
  const hiddenInScan = Math.max(0, (total ?? items.length) - items.length)

  let content: React.ReactNode
  if (items.every(isPlainObject)) {
    const rows = shown as Record<string, unknown>[]
    content = isRedirectChain(items as Record<string, unknown>[]) ? <RedirectChain hops={rows} /> : <ObjectTable rows={rows} />
  } else if (items.every((item) => typeof item === "string" && !isUrl(item) && item.length <= 40)) {
    // Korte termen (bots, talen, tags) als labels naast elkaar.
    content = (
      <div className="flex flex-wrap gap-1">
        {shown.map((item, index) => (
          <Pill key={`${index}-${item}`}>{String(item)}</Pill>
        ))}
      </div>
    )
  } else {
    content = (
      <ul className="divide-y rounded-md border bg-card">
        {shown.map((item, index) => (
          <li key={index} className="min-w-0 px-3 py-1.5">
            {isScalar(item) ? <ScalarValue name={name} value={item} /> : <span className="break-words">{inlineText(item)}</span>}
          </li>
        ))}
      </ul>
    )
  }

  return (
    <div className="space-y-1">
      {content}
      {hiddenHere > 0 ? (
        <button type="button" onClick={() => setExpanded(true)} className="text-xs text-primary hover:underline">
          en nog {hiddenHere + hiddenInScan}…
        </button>
      ) : (
        hiddenInScan > 0 && <p className="text-xs text-muted-foreground">en nog {hiddenInScan}…</p>
      )}
    </div>
  )
}

/** Stappen van een redirect: {url, status, location} en als laatste {url, status, final: true}. */
function isRedirectChain(items: Record<string, unknown>[]) {
  return items.every((hop) => typeof hop.url === "string" && ("location" in hop || "final" in hop))
}

function RedirectChain({ hops }: { hops: Record<string, unknown>[] }) {
  return (
    <ol className="divide-y rounded-md border bg-card">
      {hops.map((hop, index) => (
        <li key={`${index}-${String(hop.url)}`} className="flex min-w-0 flex-wrap items-center gap-2 px-3 py-1.5">
          <span className="w-4 shrink-0 text-muted-foreground tabular-nums">{index + 1}.</span>
          {typeof hop.status === "number" ? <HttpStatusBadge status={hop.status} /> : <Pill>—</Pill>}
          <PageLink url={String(hop.url)} />
          {hop.final ? <span className="text-muted-foreground">eindbestemming</span> : null}
        </li>
      ))}
    </ol>
  )
}

/** Kleine objecten als tabel; kolommen = alle sleutels in volgorde van voorkomen. */
function ObjectTable({ rows }: { rows: Record<string, unknown>[] }) {
  const columns: string[] = []
  for (const row of rows) {
    for (const [key, value] of Object.entries(row)) {
      if (!HIDDEN_KEYS.has(key) && !columns.includes(key) && !isEmpty(value)) columns.push(key)
    }
  }
  if (!columns.length) return null
  return (
    <div className="overflow-x-auto rounded-md border bg-card">
      <table className="w-full">
        <thead className="bg-muted/50 text-muted-foreground">
          <tr>
            {columns.map((key) => (
              <th key={key} className="px-3 py-1.5 text-left font-medium">
                {labelOf(key)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y">
          {rows.map((row, index) => (
            <tr key={index} className="align-top">
              {columns.map((key) => (
                <td key={key} className="max-w-96 px-3 py-1.5">
                  <ScalarValue name={key} value={row[key]} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
