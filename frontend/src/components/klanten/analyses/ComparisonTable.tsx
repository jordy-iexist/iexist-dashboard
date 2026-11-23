"use client"

import { useState } from "react"
import { ChevronDown, ChevronUp, Loader2 } from "lucide-react"

import { PageLink } from "@/components/livegang/comparison-parts"
import {
  CardMessage,
  ResultCard,
  YesNo,
  formatCompact,
  formatInt,
  formatLcp,
  shortUrl,
  type ResultCardState,
} from "@/components/klanten/analyses/result-parts"
import {
  EXCLUDE_REASON_LABELS,
  FETCH_STATUS_LABELS,
  FLAG_METRIC_LABELS,
  PAGE_TYPE_LABELS,
  type FlagMetric,
  type KeywordDetail,
  type MedianRow,
  type Module,
  type OwnPageRow,
  type PageRow,
} from "@/lib/competitor-analysis"
import { cn } from "@/lib/utils"

/** Zoveel concurrenten staan er standaard; de rest klapt uit. */
const VISIBLE_ROWS = 5

const th = "px-3 py-2 text-left font-medium whitespace-nowrap"
const thRight = "px-3 py-2 text-right font-medium whitespace-nowrap"
const td = "px-3 py-2 align-top"
const tdRight = "px-3 py-2 text-right align-top tabular-nums whitespace-nowrap"

/** Korte namen voor veelvoorkomende schema.org-types ("FAQPage" → "FAQ"). */
const SCHEMA_SHORT: Record<string, string> = {
  FAQPage: "FAQ",
  BreadcrumbList: "Breadcrumb",
  WebPage: "WebPage",
  LocalBusiness: "LocalBusiness",
  ProfessionalService: "Service",
}

function shortSchema(type: string) {
  return SCHEMA_SHORT[type] ?? type
}

/** Kolommen die met de gekozen onderdelen zichtbaar zijn. */
type Columns = { onpage: boolean; authority: boolean; tech: boolean }

function columnCount(columns: Columns) {
  return 3 + (columns.onpage ? 3 : 0) + (columns.tech ? 2 : 0) + (columns.authority ? 2 : 0)
}

/** Waarom de on-page-kolommen van een pagina leeg zijn; null = de pagina is uitgelezen. */
function missingReason(page: PageRow) {
  if (page.fetch_status === null) return "Nog niet opgehaald"
  if (page.fetch_status === "ok") return null
  return page.fetch_error?.trim() || FETCH_STATUS_LABELS[page.fetch_status]
}

/** Streepje met de reden als toelichting (ook voor schermlezers). */
function Dash({ reason }: { reason: string }) {
  return (
    <span className="text-muted-foreground" title={reason}>
      <span aria-hidden="true">—</span>
      <span className="sr-only">{reason}</span>
    </span>
  )
}

/** Waarde van de eigen pagina; rood (en met tekst) als hij duidelijk onder de mediaan ligt. */
function Flagged({ flagged, metric, children }: { flagged: boolean; metric: FlagMetric; children: React.ReactNode }) {
  if (!flagged) return <>{children}</>
  const hint = `${FLAG_METRIC_LABELS[metric]}: duidelijk onder de mediaan van de concurrenten`
  return (
    <span className="font-semibold text-red-700 dark:text-red-400" title={hint}>
      {children}
      <span className="sr-only"> ({hint})</span>
    </span>
  )
}

function SchemaList({ types }: { types: string[] }) {
  if (types.length === 0) return <YesNo value={false} no="Geen schema" />
  const shown = types.slice(0, 2).map(shortSchema).join(", ")
  const rest = types.length - 2
  return (
    <span title={types.join(", ")} className="whitespace-nowrap">
      {shown}
      {rest > 0 && <span className="text-muted-foreground"> +{rest}</span>}
    </span>
  )
}

/** De meetcellen van één pagina (concurrent of eigen). */
function MetricCells({ page, columns, flags }: { page: PageRow; columns: Columns; flags?: OwnPageRow["flags"] }) {
  const reason = missingReason(page)
  const flag = (metric: FlagMetric) => Boolean(flags?.[metric])
  const lcpReason = page.lcp_error?.trim() || (reason ? reason : "Nog niet gemeten")

  return (
    <>
      {columns.onpage && (
        <>
          <td className={tdRight}>
            {reason ? <Dash reason={reason} /> : <Flagged flagged={flag("words")} metric="words">{formatInt(page.words)}</Flagged>}
          </td>
          <td className={tdRight}>
            {reason ? <Dash reason={reason} /> : <Flagged flagged={flag("h2_count")} metric="h2_count">{formatInt(page.h2_count)}</Flagged>}
          </td>
          <td className={cn(td, "text-center")}>
            {reason ? (
              <Dash reason={reason} />
            ) : (
              <Flagged flagged={flag("faq")} metric="faq">
                <YesNo value={page.has_faq} yes="FAQ aanwezig" no="Geen FAQ" />
              </Flagged>
            )}
          </td>
        </>
      )}
      {columns.tech && (
        <td className={td}>
          {reason ? <Dash reason={reason} /> : <Flagged flagged={flag("schema")} metric="schema"><SchemaList types={page.schema_types} /></Flagged>}
        </td>
      )}
      {columns.authority && (
        <>
          <td className={tdRight}>
            <Flagged flagged={flag("refdomains")} metric="refdomains">
              <span title={page.refdomains != null ? `${formatInt(page.refdomains)} verwijzende domeinen` : undefined}>
                {formatCompact(page.refdomains)}
              </span>
            </Flagged>
          </td>
          <td className={tdRight}>
            <Flagged flagged={flag("domain_rating")} metric="domain_rating">{formatInt(page.domain_rating)}</Flagged>
          </td>
        </>
      )}
      {columns.tech && (
        <td className={tdRight}>
          {page.lcp_ms == null ? <Dash reason={lcpReason} /> : <Flagged flagged={flag("lcp_ms")} metric="lcp_ms">{formatLcp(page.lcp_ms)}</Flagged>}
        </td>
      )}
    </>
  )
}

/** Toelichtingen onder de URL: uitgesloten, niet opgehaald, mogelijk niet leesbaar. */
function PageNotes({ page }: { page: PageRow }) {
  const notes: string[] = []
  if (page.is_excluded) {
    notes.push(`Telt niet mee: ${page.exclude_reason ? EXCLUDE_REASON_LABELS[page.exclude_reason].toLowerCase() : "uitgesloten"}`)
  }
  const reason = missingReason(page)
  if (reason && page.fetch_status !== null) notes.push(reason)
  if (page.unreadable) notes.push("Mogelijk niet leesbaar, telt niet mee")
  if (notes.length === 0) return null
  return <p className="mt-0.5 text-xs text-muted-foreground">{notes.join(" · ")}</p>
}

function PageCell({ page, prefix }: { page: PageRow; prefix?: string }) {
  return (
    <td className={cn(td, "max-w-72 min-w-48")}>
      <div className="flex min-w-0 items-baseline gap-1" title={page.serp_title ?? page.url}>
        {prefix && <span className="shrink-0 font-semibold">{prefix}</span>}
        <PageLink url={page.url} label={shortUrl(page.url)} />
      </div>
      <PageNotes page={page} />
    </td>
  )
}

function TypeCell({ page }: { page: PageRow }) {
  return (
    <td className={cn(td, "whitespace-nowrap text-muted-foreground")}>
      {page.page_type ? PAGE_TYPE_LABELS[page.page_type] : "—"}
    </td>
  )
}

function CompetitorRow({ page, index, columns }: { page: PageRow; index: number; columns: Columns }) {
  return (
    <tr className={cn(page.is_excluded && "bg-muted/30 text-muted-foreground [&_a]:text-muted-foreground")}>
      <td className={cn(tdRight, "text-muted-foreground")}>{page.position ?? index + 1}</td>
      <PageCell page={page} />
      <TypeCell page={page} />
      <MetricCells page={page} columns={columns} />
    </tr>
  )
}

function MedianCells({ median, columns }: { median: MedianRow; columns: Columns }) {
  const ratio = (count: number) => (median.total > 0 ? `${count}/${median.total}` : "—")
  return (
    <>
      {columns.onpage && (
        <>
          <td className={tdRight}>{formatInt(median.words)}</td>
          <td className={tdRight}>{formatInt(median.h2_count)}</td>
          <td className={cn(td, "text-center whitespace-nowrap")} title={median.total > 0 ? `${median.faq_count} van de ${median.total} pagina's hebben een FAQ` : undefined}>
            {ratio(median.faq_count)}
          </td>
        </>
      )}
      {columns.tech && (
        <td className={cn(td, "whitespace-nowrap")} title={median.total > 0 ? `${median.schema_count} van de ${median.total} pagina's hebben schema` : undefined}>
          {ratio(median.schema_count)}
          {median.total > 0 && median.schema_top && <span className="text-muted-foreground"> {shortSchema(median.schema_top)}</span>}
        </td>
      )}
      {columns.authority && (
        <>
          <td className={tdRight}>{formatCompact(median.refdomains)}</td>
          <td className={tdRight}>{formatInt(median.domain_rating)}</td>
        </>
      )}
      {columns.tech && <td className={tdRight}>{formatLcp(median.lcp_ms)}</td>}
    </>
  )
}

/** Kaart "Jij vs. de top X": concurrenten, mediaan en de eigen pagina naast elkaar. */
export function ComparisonTable({
  detail,
  modules,
  topN,
  running,
  tableState,
  error,
}: {
  detail: KeywordDetail
  modules: readonly Module[]
  topN: number
  /** De analyse loopt nog: de tabel vult zich terwijl pagina's binnenkomen. */
  running: boolean
  /** Toestand als er (nog) geen rijen zijn, bijv. "unavailable" bij een mislukte SERP. */
  tableState: ResultCardState
  error?: string | null
}) {
  const [expanded, setExpanded] = useState(false)
  const columns: Columns = {
    onpage: modules.includes("onpage"),
    authority: modules.includes("authority"),
    tech: modules.includes("tech"),
  }
  const span = columnCount(columns)
  const { pages, own, median } = detail
  const hidden = pages.slice(VISIBLE_ROWS)
  const visible = expanded ? pages : pages.slice(0, VISIBLE_ROWS)
  const anyExcluded = pages.some((page) => page.is_excluded || page.unreadable)
  const firstHidden = hidden[0]?.position ?? VISIBLE_ROWS + 1
  const lastHidden = hidden.at(-1)?.position ?? pages.length

  const description = (
    <>
      Rode waarden liggen duidelijk onder de mediaan van de concurrenten.
      {anyExcluded && " Gedempte rijen tellen niet mee in de mediaan."}
    </>
  )

  return (
    <ResultCard
      id="comparison"
      title={`Jij vs. de top ${topN}`}
      description={description}
      aside={
        running ? (
          <span role="status" className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
            <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
            Wordt bijgewerkt
          </span>
        ) : undefined
      }
    >
      {tableState !== "filled" ? (
        <CardMessage
          state={tableState}
          error={error}
          texts={{
            pending: "De zoekresultaten en pagina's worden opgehaald…",
            empty: "Ahrefs gaf geen zoekresultaten voor dit zoekwoord; er is niets om mee te vergelijken.",
            not_configured: "De koppeling met Ahrefs is niet ingesteld, dus de top van Google kon niet worden opgehaald.",
            unavailable: "De zoekresultaten konden niet worden opgehaald.",
          }}
        />
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-sm">
            <caption className="sr-only">
              Vergelijking van de eigen pagina met de top {topN} van Google voor “{detail.keyword}”
            </caption>
            <thead className="bg-muted/50 text-xs text-muted-foreground">
              <tr>
                <th scope="col" className={thRight}>
                  #
                </th>
                <th scope="col" className={th}>
                  Pagina
                </th>
                <th scope="col" className={th}>
                  Type
                </th>
                {columns.onpage && (
                  <>
                    <th scope="col" className={thRight}>
                      Woorden
                    </th>
                    <th scope="col" className={thRight}>
                      H2&apos;s
                    </th>
                    <th scope="col" className={cn(th, "text-center")}>
                      FAQ
                    </th>
                  </>
                )}
                {columns.tech && (
                  <th scope="col" className={th}>
                    Schema
                  </th>
                )}
                {columns.authority && (
                  <>
                    <th scope="col" className={thRight}>
                      <abbr title="Verwijzende domeinen" className="no-underline">
                        Ref. dom.
                      </abbr>
                    </th>
                    <th scope="col" className={thRight}>
                      <abbr title="Domain Rating (Ahrefs)" className="no-underline">
                        DR
                      </abbr>
                    </th>
                  </>
                )}
                {columns.tech && (
                  <th scope="col" className={thRight}>
                    <abbr title="Largest Contentful Paint (mobiel)" className="no-underline">
                      LCP
                    </abbr>
                  </th>
                )}
              </tr>
            </thead>
            <tbody className="divide-y">
              {pages.length === 0 && (
                <tr>
                  <td colSpan={span} className={cn(td, "text-muted-foreground")}>
                    {running ? "De zoekresultaten worden opgehaald…" : "Geen concurrenten gevonden."}
                  </td>
                </tr>
              )}
              {visible.map((page, index) => (
                <CompetitorRow key={page.id} page={page} index={index} columns={columns} />
              ))}
              {hidden.length > 0 && (
                <tr>
                  <td colSpan={span} className="px-3 py-1.5">
                    <button
                      type="button"
                      aria-expanded={expanded}
                      onClick={() => setExpanded((value) => !value)}
                      className="inline-flex items-center gap-1 rounded-sm text-xs font-medium text-primary outline-none hover:underline focus-visible:ring-[3px] focus-visible:ring-ring/50"
                    >
                      {expanded ? (
                        <>
                          <ChevronUp className="size-3.5" aria-hidden="true" />
                          Posities {firstHidden} t/m {lastHidden} verbergen
                        </>
                      ) : (
                        <>
                          <ChevronDown className="size-3.5" aria-hidden="true" />+ posities {firstHidden} t/m {lastHidden} tonen
                        </>
                      )}
                    </button>
                  </td>
                </tr>
              )}
              <tr className="bg-muted/50 font-medium">
                <td className={td} />
                <th scope="row" colSpan={2} className={cn(td, "text-left font-semibold")}>
                  Mediaan top {topN}
                  <span className="block text-xs font-normal text-muted-foreground">
                    {median.total > 0
                      ? `Over ${median.total} meegetelde ${median.total === 1 ? "pagina" : "pagina's"}`
                      : "Nog geen meegetelde pagina's"}
                  </span>
                </th>
                <MedianCells median={median} columns={columns} />
              </tr>
              {own ? (
                <tr className="border-t-2 border-t-primary/40 bg-primary/5">
                  <td className={cn(tdRight, "font-semibold")} title={own.position == null ? "Niet gevonden in de zoekresultaten" : undefined}>
                    {own.position ?? "—"}
                  </td>
                  <PageCell page={own} prefix="Jij:" />
                  <TypeCell page={own} />
                  <MetricCells page={own} columns={columns} flags={own.flags} />
                </tr>
              ) : (
                <tr className="border-t-2 border-t-primary/40 bg-primary/5">
                  <td className={td} />
                  <td colSpan={span - 1} className={cn(td, "font-medium")}>
                    {detail.target_url === null ? (
                      <>
                        Nog geen pagina voor dit zoekwoord
                        <span className="block text-xs font-normal text-muted-foreground">
                          De mediaan laat zien waar een nieuwe pagina ongeveer aan moet voldoen.
                        </span>
                      </>
                    ) : (
                      <>
                        <span className="flex min-w-0 items-baseline gap-1">
                          <span className="shrink-0 font-semibold">Jij:</span>
                          <PageLink url={detail.target_url} label={shortUrl(detail.target_url)} />
                        </span>
                        <span className="block text-xs font-normal text-muted-foreground">
                          {running ? "De eigen pagina wordt nog opgehaald…" : "De eigen pagina kon niet worden opgehaald."}
                        </span>
                      </>
                    )}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </ResultCard>
  )
}
