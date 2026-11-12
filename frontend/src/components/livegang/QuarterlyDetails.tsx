"use client"

import { ArrowDown, ArrowUp, ExternalLink, Minus, Plug } from "lucide-react"

import { Evidence } from "@/components/livegang/ChecklistTab"
import { AutoStatusBadge, CompactStat, HttpStatusBadge, Pill, StatGrid } from "@/components/livegang/shared"
import {
  CATEGORY_LABELS,
  formatDateTime,
  type AiCheckChange,
  type ChecklistItem,
  type GscMetricChange,
  type GscMovers,
  type GscSpan,
  type NewPagesDetails,
  type QuarterlyChecklist,
  type QuarterlyComparison,
  type SchemaValidationDetails,
} from "@/lib/launch-checklist"
import { cn } from "@/lib/utils"

const MAX_ROWS = 50
const linkClass = "inline-flex min-w-0 items-center gap-1 break-all text-primary hover:underline"

function PageLink({ url, label }: { url: string; label?: string }) {
  return (
    <a href={url} target="_blank" rel="noreferrer noopener" className={linkClass}>
      <span className="truncate">{label ?? url}</span>
      <ExternalLink className="size-3 shrink-0" />
    </a>
  )
}

function formatNumber(value: number | null | undefined, digits = 0) {
  return value == null ? "—" : value.toLocaleString("nl-NL", { maximumFractionDigits: digits })
}

/** Verschil met pijl; `higherIsBetter` bepaalt de kleur. */
function Delta({ value, higherIsBetter = true, digits = 0 }: { value: number | null | undefined; higherIsBetter?: boolean; digits?: number }) {
  if (value == null) return <span className="text-muted-foreground">—</span>
  if (value === 0) return <span className="inline-flex items-center gap-0.5 text-muted-foreground"><Minus className="size-3" />0</span>
  const good = value > 0 === higherIsBetter
  const Icon = value > 0 ? ArrowUp : ArrowDown
  return (
    <span className={cn("inline-flex items-center gap-0.5 font-medium", good ? "text-green-700 dark:text-green-400" : "text-red-700 dark:text-red-400")}>
      <Icon className="size-3" />
      {formatNumber(Math.abs(value), digits)}
    </span>
  )
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">{children}</h3>
}

function Table({ head, children }: { head: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="overflow-x-auto rounded-lg border bg-card">
      <table className="w-full text-sm">
        <thead className="bg-muted/50 text-xs text-muted-foreground">{head}</thead>
        <tbody className="divide-y">{children}</tbody>
      </table>
    </div>
  )
}

const th = "px-3 py-2 text-left font-medium"
const thRight = "px-3 py-2 text-right font-medium"
const td = "px-3 py-2"
const tdRight = "px-3 py-2 text-right tabular-nums"

// --- details per checklistpunt ---------------------------------------------------

/** Detailweergave van een fase 4-punt in de checklist; null = de standaard evidence-lijst. */
export function QuarterlyItemDetails({ item }: { item: ChecklistItem }) {
  const details = item.auto?.details
  if (!details || typeof details !== "object") return null
  if (item.key === "c4_new_pages") return <NewPagesList details={details as NewPagesDetails} />
  if (item.key === "c4_schema_validation") return <SchemaList details={details as SchemaValidationDetails} />
  if (item.key === "c4_ai_scan") {
    const checks = (details as { checks?: AiCheckChange[] }).checks ?? []
    const changed = checks.filter((c) => c.change !== "same")
    return changed.length ? <AiChangeList checks={changed} /> : <Evidence values={item.auto?.evidence ?? []} />
  }
  return null
}

function NewPagesList({ details }: { details: NewPagesDetails }) {
  const problems = details.new.filter((r) => r.result !== "ok")
  const fine = details.new.length - problems.length
  return (
    <div className="space-y-3 text-xs">
      {details.broken.length > 0 && (
        <div>
          <p className="mb-1 font-medium text-muted-foreground">Werkte eerder, geeft nu een fout ({details.broken_total})</p>
          <ul className="divide-y rounded-md border bg-card">
            {details.broken.slice(0, MAX_ROWS).map((row) => (
              <li key={row.url} className="flex min-w-0 items-center gap-2 px-2 py-1.5">
                <HttpStatusBadge status={row.status_code} />
                <span className="shrink-0 text-muted-foreground">was {row.before ?? "—"}</span>
                <PageLink url={row.url} label={row.path} />
              </li>
            ))}
          </ul>
        </div>
      )}
      {problems.length > 0 && (
        <div>
          <p className="mb-1 font-medium text-muted-foreground">Nieuwe pagina&apos;s met een probleem ({problems.length})</p>
          <ul className="divide-y rounded-md border bg-card">
            {problems.slice(0, MAX_ROWS).map((row) => (
              <li key={row.url} className="space-y-0.5 px-2 py-1.5">
                <div className="flex min-w-0 items-center gap-2">
                  <Pill tone={row.result === "error" ? "red" : "amber"}>{row.result === "error" ? "Fout" : "Let op"}</Pill>
                  <PageLink url={row.url} label={row.path} />
                </div>
                <p className="text-muted-foreground">{row.problems.join(" · ")}</p>
              </li>
            ))}
          </ul>
        </div>
      )}
      {details.new_total > 0 && (
        <p className="text-muted-foreground">
          {details.new_total} nieuwe pagina&apos;s in totaal, waarvan {fine} zonder problemen.
        </p>
      )}
      {details.removed_total > 0 && (
        <details>
          <summary className="cursor-pointer text-muted-foreground">
            {details.removed_total} pagina&apos;s niet meer gevonden in deze scan
          </summary>
          <ul className="mt-1 space-y-0.5">
            {details.removed.slice(0, MAX_ROWS).map((url) => (
              <li key={url}><PageLink url={url} /></li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}

function SchemaList({ details }: { details: SchemaValidationDetails }) {
  return (
    <div className="space-y-2 text-xs">
      <p className="text-muted-foreground">
        {details.checked} pagina&apos;s gecontroleerd, {details.with_schema} met JSON-LD · {details.error_pages} met fouten ·{" "}
        {details.warning_pages} met een aandachtspunt.
      </p>
      {details.pages.length > 0 && (
        <ul className="divide-y rounded-md border bg-card">
          {details.pages.slice(0, MAX_ROWS).map((row) => (
            <li key={row.url} className="space-y-1 px-2 py-1.5">
              <div className="flex min-w-0 items-center gap-2">
                <Pill tone={row.result === "error" ? "red" : "amber"}>{row.result === "error" ? "Fout" : "Let op"}</Pill>
                <PageLink url={row.url} label={row.path} />
              </div>
              <ul className="space-y-0.5 pl-1 text-muted-foreground">
                {row.invalid_blocks > 0 && <li>{row.invalid_blocks}× ongeldige JSON in een ld+json-blok</li>}
                {row.problems.map((p, index) => (
                  <li key={index}>
                    <span className={cn("font-medium", p.severity === "error" ? "text-red-700 dark:text-red-400" : "text-amber-700 dark:text-amber-400")}>
                      {p.type}
                    </span>
                    {p.missing.length > 0 && <> · mist {p.missing.join(", ")}</>}
                    {p.problems.length > 0 && <> · {p.problems.join("; ")}</>}
                  </li>
                ))}
                {row.lost_types.length > 0 && <li>Verdwenen sinds de vorige ronde: {row.lost_types.join(", ")}</li>}
              </ul>
            </li>
          ))}
        </ul>
      )}
      <p className="text-muted-foreground">
        Controleer een pagina ook met de{" "}
        <a href="https://search.google.com/test/rich-results" target="_blank" rel="noreferrer noopener" className="text-primary hover:underline">
          Rich Results Test
        </a>
        .
      </p>
    </div>
  )
}

const CHANGE_LABELS: Record<AiCheckChange["change"], { label: string; tone: "green" | "red" | "muted" | "blue" }> = {
  better: { label: "Verbeterd", tone: "green" },
  worse: { label: "Verslechterd", tone: "red" },
  same: { label: "Gelijk", tone: "muted" },
  new: { label: "Nieuw", tone: "blue" },
}

function AiChangeList({ checks }: { checks: AiCheckChange[] }) {
  return (
    <ul className="divide-y rounded-md border bg-card text-xs">
      {checks.map((check) => (
        <li key={check.key} className="flex flex-wrap items-center gap-2 px-2 py-1.5">
          <span className="min-w-32 font-medium">{check.label}</span>
          <AutoStatusBadge status={check.before ?? undefined} />
          <span className="text-muted-foreground">→</span>
          <AutoStatusBadge status={check.after} />
          <Pill tone={CHANGE_LABELS[check.change].tone}>{CHANGE_LABELS[check.change].label}</Pill>
          {check.message && <span className="w-full text-muted-foreground">{check.message}</span>}
        </li>
      ))}
    </ul>
  )
}

// --- tabblad Vergelijking -----------------------------------------------------------

export function ComparisonTab({ checklist }: { checklist: QuarterlyChecklist }) {
  const comparison = checklist.comparison
  if (!comparison) {
    return <p className="text-sm text-muted-foreground">Nog geen vergelijking: start een scan voor deze ronde.</p>
  }
  return (
    <div className="space-y-6">
      <ComparisonSummary comparison={comparison} periodLabel={checklist.period_label} />
      <AiSection comparison={comparison} />
      <RankingsSection comparison={comparison} />
      <SearchConsoleSection comparison={comparison} />
      <AhrefsSection comparison={comparison} />
      <IssuesSection comparison={comparison} />
      <SourcesNote checklist={checklist} />
    </div>
  )
}

function ComparisonSummary({ comparison, periodLabel }: { comparison: QuarterlyComparison; periodLabel: string }) {
  const { ai, issues, pages, base } = comparison
  const aiDelta = ai.before != null && ai.after != null ? ai.after - ai.before : null
  return (
    <section className="space-y-2">
      <SectionTitle>
        Ronde {periodLabel} t.o.v. {base ? base.label.toLowerCase() : "—"}
      </SectionTitle>
      {base?.completed_at && <p className="text-xs text-muted-foreground">Basis gescand op {formatDateTime(base.completed_at)}.</p>}
      <StatGrid className="grid-cols-2 sm:grid-cols-3 xl:grid-cols-6">
        <CompactStat
          label="AI-score"
          value={<span className="inline-flex items-baseline gap-2">{ai.after ?? "—"} <span className="text-xs"><Delta value={aiDelta} /></span></span>}
          hint={ai.before != null ? `was ${ai.before}` : undefined}
        />
        <CompactStat
          label="Actiepunten"
          value={<span className="inline-flex items-baseline gap-2">{issues.after} <span className="text-xs"><Delta value={issues.after - issues.before} higherIsBetter={false} /></span></span>}
          hint={`was ${issues.before}`}
        />
        <CompactStat label="Pagina's" value={pages.after} hint={`was ${pages.before}`} />
        <CompactStat label="Nieuwe pagina's" value={pages.new} />
        <CompactStat label="Niet meer gevonden" value={pages.removed} tone={pages.removed ? "warn" : undefined} />
        <CompactStat label="Nu kapot" value={pages.broken} tone={pages.broken ? "bad" : "good"} />
      </StatGrid>
    </section>
  )
}

function AiSection({ comparison }: { comparison: QuarterlyComparison }) {
  const checks = comparison.ai.checks
  if (!checks.length) return null
  return (
    <section className="space-y-2">
      <SectionTitle>AI-vindbaarheid</SectionTitle>
      <Table
        head={
          <tr>
            <th className={th}>Check</th>
            <th className={th}>Vorige</th>
            <th className={th}>Nu</th>
            <th className={th}>Verandering</th>
          </tr>
        }
      >
        {checks.map((check) => (
          <tr key={check.key}>
            <td className={td}>
              <p className="font-medium">{check.label}</p>
              {check.message && <p className="text-xs text-muted-foreground">{check.message}</p>}
            </td>
            <td className={td}><AutoStatusBadge status={check.before ?? undefined} /></td>
            <td className={td}><AutoStatusBadge status={check.after} /></td>
            <td className={td}><Pill tone={CHANGE_LABELS[check.change].tone}>{CHANGE_LABELS[check.change].label}</Pill></td>
          </tr>
        ))}
      </Table>
    </section>
  )
}

function RankingsSection({ comparison }: { comparison: QuarterlyComparison }) {
  const rankings = comparison.rankings
  return (
    <section className="space-y-2">
      <SectionTitle>Posities (SEO-tracker)</SectionTitle>
      {!rankings ? (
        <p className="text-sm text-muted-foreground">
          Geen posities: voor deze klant worden geen zoekwoorden gevolgd in de SEO-tracker.
        </p>
      ) : (
        <>
          <StatGrid className="grid-cols-2 sm:grid-cols-5">
            <CompactStat label="Zoekwoorden" value={rankings.keywords} />
            <CompactStat label="In top 3" value={rankings.top3} />
            <CompactStat label="In top 10" value={rankings.top10} />
            <CompactStat label="Gestegen" value={rankings.improved} tone={rankings.improved ? "good" : undefined} />
            <CompactStat label="Gedaald" value={rankings.declined} tone={rankings.declined ? "bad" : undefined} />
          </StatGrid>
          {rankings.compared === 0 && (
            <p className="text-xs text-muted-foreground">Er zijn geen metingen van vóór de basisdatum om mee te vergelijken.</p>
          )}
          <Table
            head={
              <tr>
                <th className={th}>Zoekwoord</th>
                <th className={thRight}>Toen</th>
                <th className={thRight}>Nu</th>
                <th className={thRight}>Verschil</th>
                <th className={th}>Pagina</th>
              </tr>
            }
          >
            {rankings.rows.slice(0, MAX_ROWS).map((row) => (
              <tr key={row.keyword}>
                <td className={td}>{row.keyword}</td>
                <td className={tdRight}>{row.before ?? "—"}</td>
                <td className={tdRight}>{row.after ?? ">100"}</td>
                <td className={tdRight}><Delta value={row.delta} /></td>
                <td className={cn(td, "max-w-64")}>{row.url ? <PageLink url={row.url} /> : <span className="text-muted-foreground">—</span>}</td>
              </tr>
            ))}
          </Table>
          {rankings.last_checked_at && (
            <p className="text-xs text-muted-foreground">Laatste meting: {formatDateTime(rankings.last_checked_at)}.</p>
          )}
        </>
      )}
    </section>
  )
}

const dayFormat = new Intl.DateTimeFormat("nl-NL", { day: "numeric", month: "short", year: "numeric" })

function formatSpan(span: GscSpan) {
  const day = (value: string) => dayFormat.format(new Date(`${value}T00:00:00`))
  return `${day(span.start)} – ${day(span.end)}`
}

/** CTR is een fractie (0,035 = 3,5%); positie heeft één decimaal; de rest zijn aantallen. */
function formatGscValue(key: GscMetricChange["key"], value: number | null) {
  if (value == null) return "—"
  if (key === "ctr") return `${formatNumber(value * 100, 1)}%`
  return formatNumber(value, key === "position" ? 1 : 0)
}

function GscPercent({ value, higherIsBetter = true }: { value: number | null; higherIsBetter?: boolean }) {
  if (value == null) return null
  const good = value === 0 ? null : value > 0 === higherIsBetter
  return (
    <span
      className={cn(
        "ml-1.5 text-xs",
        good === null ? "text-muted-foreground" : good ? "text-green-700 dark:text-green-400" : "text-red-700 dark:text-red-400"
      )}
    >
      {value > 0 ? "+" : ""}
      {formatNumber(value, 1)}%
    </span>
  )
}

function GscMoversTable({ title, rows, isUrl }: { title: string; rows: GscMovers["risers"]; isUrl: boolean }) {
  if (!rows.length) return null
  return (
    <div className="min-w-0 space-y-1">
      <p className="text-xs font-medium text-muted-foreground">{title}</p>
      <Table
        head={
          <tr>
            <th className={th}>{isUrl ? "Pagina" : "Zoekopdracht"}</th>
            <th className={thRight}>Vorige</th>
            <th className={thRight}>Nu</th>
            <th className={thRight}>Verschil</th>
            <th className={thRight}>Positie</th>
          </tr>
        }
      >
        {rows.slice(0, 10).map((row) => (
          <tr key={row.key}>
            <td className={cn(td, "max-w-64")}>
              {isUrl ? <PageLink url={row.key} /> : <span className="break-words">{row.key}</span>}
            </td>
            <td className={tdRight}>{formatNumber(row.clicks_prev)}</td>
            <td className={tdRight}>{formatNumber(row.clicks)}</td>
            <td className={tdRight}><Delta value={row.delta} /></td>
            <td className={tdRight}>{formatNumber(row.position, 1)}</td>
          </tr>
        ))}
      </Table>
    </div>
  )
}

function SearchConsoleSection({ comparison }: { comparison: QuarterlyComparison }) {
  const gsc = comparison.search_console
  if (!gsc) {
    return (
      <section className="space-y-2">
        <SectionTitle>Search Console (Google)</SectionTitle>
        <p className="text-sm text-muted-foreground">
          Geen Search Console-data in deze scan: de koppeling ontbreekt of er is geen property voor dit domein gevonden
          (zie de waarschuwingen bij de scan).
        </p>
      </section>
    )
  }
  const problemSitemaps = gsc.sitemaps?.rows.filter((s) => s.errors || s.warnings) ?? []
  const notIndexed = gsc.inspection?.not_indexed ?? []
  return (
    <section className="space-y-3">
      <SectionTitle>Search Console (Google)</SectionTitle>
      <p className="text-xs text-muted-foreground">
        <span className="font-mono">{gsc.property}</span> · {formatSpan(gsc.period)} t.o.v. de {gsc.previous.days} dagen
        ervoor ({formatSpan(gsc.previous)}). Klikken in Google Zoeken (web), niet de vergelijking met de basis-scan.
      </p>

      {gsc.has_performance ? (
        <Table
          head={
            <tr>
              <th className={th}>Cijfer</th>
              <th className={thRight}>Vorige periode</th>
              <th className={thRight}>Deze periode</th>
              <th className={thRight}>Verschil</th>
              <th className={thRight}>Zelfde periode vorig jaar</th>
            </tr>
          }
        >
          {gsc.metrics.map((metric) => {
            const higherIsBetter = metric.key !== "position"
            // CTR-verschil in procentpunten; de overige cijfers in hun eigen eenheid.
            const delta = metric.delta == null ? null : metric.key === "ctr" ? metric.delta * 100 : metric.delta
            return (
              <tr key={metric.key}>
                <td className={td}>{metric.label}</td>
                <td className={tdRight}>{formatGscValue(metric.key, metric.before)}</td>
                <td className={tdRight}>{formatGscValue(metric.key, metric.after)}</td>
                <td className={tdRight}>
                  <Delta value={delta} higherIsBetter={higherIsBetter} digits={metric.key === "ctr" || metric.key === "position" ? 1 : 0} />
                  {(metric.key === "clicks" || metric.key === "impressions") && <GscPercent value={metric.pct} />}
                </td>
                <td className={tdRight}>
                  {formatGscValue(metric.key, metric.last_year)}
                  {(metric.key === "clicks" || metric.key === "impressions") && <GscPercent value={metric.pct_last_year} />}
                </td>
              </tr>
            )
          })}
        </Table>
      ) : (
        <p className="text-sm text-muted-foreground">De prestatiecijfers konden niet worden opgehaald (zie de waarschuwingen).</p>
      )}

      <div className="grid gap-4 xl:grid-cols-2">
        <GscMoversTable title="Zoekopdrachten: grootste dalers in klikken" rows={gsc.queries.fallers} isUrl={false} />
        <GscMoversTable title="Zoekopdrachten: grootste stijgers in klikken" rows={gsc.queries.risers} isUrl={false} />
        <GscMoversTable title="Pagina's: grootste dalers in klikken" rows={gsc.pages.fallers} isUrl />
        <GscMoversTable title="Pagina's: grootste stijgers in klikken" rows={gsc.pages.risers} isUrl />
      </div>

      {gsc.sitemaps && (
        <div className="space-y-1 text-sm">
          <p>
            <span className="font-medium">Sitemaps:</span>{" "}
            {gsc.sitemaps.total === 0
              ? "er is geen sitemap ingediend in Search Console."
              : `${gsc.sitemaps.total} ingediend, ${gsc.sitemaps.with_errors} met fouten, ${gsc.sitemaps.with_warnings} met waarschuwingen.`}
          </p>
          {problemSitemaps.length > 0 && (
            <ul className="divide-y rounded-md border bg-card text-xs">
              {problemSitemaps.slice(0, MAX_ROWS).map((sitemap) => (
                <li key={sitemap.path} className="flex min-w-0 flex-wrap items-center gap-2 px-2 py-1.5">
                  <Pill tone={sitemap.errors ? "red" : "amber"}>
                    {sitemap.errors
                      ? `${sitemap.errors} ${sitemap.errors === 1 ? "fout" : "fouten"}`
                      : `${sitemap.warnings} ${sitemap.warnings === 1 ? "waarschuwing" : "waarschuwingen"}`}
                  </Pill>
                  <PageLink url={sitemap.path} />
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {gsc.inspection && (
        <div className="space-y-1 text-sm">
          <p>
            <span className="font-medium">URL-inspectie:</span> {gsc.inspection.checked} URL&apos;s gecontroleerd (homepage en
            nieuwe pagina&apos;s), {gsc.inspection.indexed} geïndexeerd door Google.
          </p>
          {notIndexed.length > 0 && (
            <ul className="divide-y rounded-md border bg-card text-xs">
              {notIndexed.slice(0, MAX_ROWS).map((row) => (
                <li key={row.url} className="space-y-0.5 px-2 py-1.5">
                  <div className="flex min-w-0 items-center gap-2">
                    <Pill tone={row.state === "blocked" ? "red" : "amber"}>
                      {row.state === "blocked" ? "Geblokkeerd" : "Niet geïndexeerd"}
                    </Pill>
                    <PageLink url={row.url} />
                  </div>
                  <p className="text-muted-foreground">
                    {row.reason ?? "Reden onbekend"}
                    {row.last_crawl_time ? ` · laatst gecrawld ${formatDateTime(row.last_crawl_time)}` : ""}
                    {row.link && (
                      <>
                        {" · "}
                        <a href={row.link} target="_blank" rel="noreferrer noopener" className="text-primary hover:underline">
                          Open in Search Console
                        </a>
                      </>
                    )}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  )
}

function AhrefsSection({ comparison }: { comparison: QuarterlyComparison }) {
  const ahrefs = comparison.ahrefs
  return (
    <section className="space-y-2">
      <SectionTitle>Backlinks &amp; autoriteit (Ahrefs)</SectionTitle>
      {!ahrefs ? (
        <p className="text-sm text-muted-foreground">Geen Ahrefs-data in deze of de vorige scan.</p>
      ) : (
        <>
          {ahrefs.same_snapshot && (
            <p className="text-xs text-muted-foreground">
              Dezelfde Ahrefs-meting als de basis ({formatDateTime(ahrefs.fetched_after)}): de data is hergebruikt binnen de
              bewaartermijn, dus er is nog geen verschil te zien.
            </p>
          )}
          <Table
            head={
              <tr>
                <th className={th}>Cijfer</th>
                <th className={thRight}>Vorige</th>
                <th className={thRight}>Nu</th>
                <th className={thRight}>Verschil</th>
              </tr>
            }
          >
            {ahrefs.metrics.map((metric) => (
              <tr key={metric.key}>
                <td className={td}>{metric.label}</td>
                <td className={tdRight}>{formatNumber(metric.before, 1)}</td>
                <td className={tdRight}>{formatNumber(metric.after, 1)}</td>
                <td className={tdRight}><Delta value={metric.delta} digits={1} /></td>
              </tr>
            ))}
          </Table>
          {!!ahrefs.lost_value_urls && (
            <p className="text-xs text-muted-foreground">
              {ahrefs.lost_value_urls} pagina&apos;s met verkeer of backlinks werken niet meer (zie de actiepunten).
            </p>
          )}
        </>
      )}
    </section>
  )
}

function IssuesSection({ comparison }: { comparison: QuarterlyComparison }) {
  const rows = comparison.issues.rows.filter((r) => r.delta !== 0)
  return (
    <section className="space-y-2">
      <SectionTitle>Veranderingen in actiepunten</SectionTitle>
      {rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">Geen veranderingen in het aantal actiepunten per type.</p>
      ) : (
        <Table
          head={
            <tr>
              <th className={th}>Type</th>
              <th className={th}>Categorie</th>
              <th className={thRight}>Vorige</th>
              <th className={thRight}>Nu</th>
              <th className={thRight}>Verschil</th>
            </tr>
          }
        >
          {rows.slice(0, MAX_ROWS).map((row) => (
            <tr key={row.issue_type}>
              <td className={td}>{row.label}</td>
              <td className={cn(td, "text-xs text-muted-foreground")}>{CATEGORY_LABELS[row.category] ?? row.category}</td>
              <td className={tdRight}>{row.before}</td>
              <td className={tdRight}>{row.after}</td>
              <td className={tdRight}><Delta value={row.delta} higherIsBetter={false} /></td>
            </tr>
          ))}
        </Table>
      )}
    </section>
  )
}

const EXTERNAL_SOURCES: { key: "search_console" | "ga4" | "bing_webmaster" | null; label: string; hint: string }[] = [
  { key: "search_console", label: "Google Search Console", hint: "klikken, vertoningen, indexatiefouten" },
  { key: "ga4", label: "Google Analytics 4", hint: "sessies, conversies" },
  { key: "bing_webmaster", label: "Bing Webmaster Tools", hint: "crawlfouten, indexatie" },
  { key: null, label: "ProRankTracker", hint: "AI-zichtbaarheid per platform" },
]

function SourcesNote({ checklist }: { checklist: QuarterlyChecklist }) {
  const sources = checklist.sources
  const missing = EXTERNAL_SOURCES.filter((s) => !s.key || !sources?.[s.key])
  if (!missing.length) return null
  return (
    <section className="space-y-2 rounded-lg border border-dashed p-4">
      <h3 className="flex items-center gap-2 text-sm font-semibold">
        <Plug className="size-4 text-muted-foreground" /> Nog niet gekoppeld: zelf aanvullen in de rapportage
      </h3>
      <ul className="grid gap-1 text-sm sm:grid-cols-2">
        {missing.map((s) => (
          <li key={s.label}>
            <span className="font-medium">{s.label}</span> <span className="text-muted-foreground">· {s.hint}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}
