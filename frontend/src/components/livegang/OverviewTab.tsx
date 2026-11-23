"use client"

import ReactMarkdown from "react-markdown"
import { Bot, ChevronDown, TriangleAlert } from "lucide-react"

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { formatCount, type AhrefsScan, type LaunchScanDetail } from "@/lib/launch-checklist"
import { cn } from "@/lib/utils"

function pct(part: number, total: number) {
  return total > 0 ? `${Math.round((part / total) * 100)}%` : "—"
}

/** Groep binnen de cijfer-card: kopje met daaronder de items als lijst. */
function StatGroup({ title, footer, children }: { title: string; footer?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="px-4 py-3">
      <h3 className="pb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</h3>
      {children}
      {footer && <p className="pt-2 text-[11px] text-muted-foreground">{footer}</p>}
    </section>
  )
}

function StatRow({
  label,
  value,
  hint,
  tone,
}: {
  label: string
  value: React.ReactNode
  hint?: string
  tone?: "good" | "warn" | "bad"
}) {
  return (
    <li className="flex items-baseline justify-between gap-3 py-1.5">
      <div className="min-w-0">
        <p className="text-sm">{label}</p>
        {hint && <p className="text-[11px] text-muted-foreground">{hint}</p>}
      </div>
      <span
        className={cn(
          "shrink-0 text-sm font-semibold tabular-nums",
          tone === "good" && "text-green-700 dark:text-green-400",
          tone === "warn" && "text-amber-700 dark:text-amber-400",
          tone === "bad" && "text-red-700 dark:text-red-400",
          !tone && "text-primary"
        )}
      >
        {value}
      </span>
    </li>
  )
}

function AhrefsGroup({ data }: { data: AhrefsScan }) {
  const domain = data.domain ?? {}
  const hasDomain = domain.domain_rating != null || domain.refdomains != null || domain.org_traffic != null
  if (!hasDomain && !data.pages_with_traffic && !data.pages_with_backlinks) return null
  const value = domain.org_cost != null ? Math.round(domain.org_cost / 100) : null
  const fetched = new Date(data.fetched_at).toLocaleDateString("nl-NL", { day: "numeric", month: "short", year: "numeric" })

  return (
    <StatGroup
      title="Autoriteit & organisch (Ahrefs)"
      footer={
        <>
          Ahrefs · {data.target} · {data.country.toUpperCase()} · data van {fetched} ·{" "}
          {data.reused_from ? "overgenomen van de vorige scan (0 units)" : `${formatCount(data.units)} API-units`}
        </>
      }
    >
      <ul className="divide-y">
        <StatRow
          label="Domain Rating"
          value={domain.domain_rating != null ? Math.round(domain.domain_rating) : "—"}
          hint="Schaal 0–100"
        />
        <StatRow
          label="Verwijzende domeinen"
          value={formatCount(domain.refdomains)}
          hint={`${formatCount(domain.backlinks)} backlinks`}
        />
        <StatRow
          label="Organisch verkeer / mnd"
          value={formatCount(domain.org_traffic)}
          hint={value != null ? `Waarde circa $${formatCount(value)}` : `Land: ${data.country.toUpperCase()}`}
        />
        <StatRow
          label="Zoekwoorden"
          value={formatCount(domain.org_keywords)}
          hint={`${formatCount(domain.org_keywords_1_3)} in de top 3`}
        />
        <StatRow
          label="Pagina's met verkeer"
          value={data.pages_with_traffic}
          hint={`${data.pages_with_backlinks} met backlinks`}
        />
        <StatRow
          label="URL's met waarde die niet werken"
          value={data.lost_value_urls}
          tone={data.lost_value_urls ? "bad" : "good"}
          hint={`${data.extra_urls} URL's niet in crawl`}
        />
      </ul>
    </StatGroup>
  )
}

export function OverviewTab({ scan }: { scan: LaunchScanDetail }) {
  const stats = scan.summary_stats
  const trace = scan.agent_trace

  return (
    <div className="space-y-6">
      {scan.warnings && scan.warnings.length > 0 && (
        <div className="space-y-1 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
          {scan.warnings.map((w) => (
            <p key={w} className="flex gap-2">
              <TriangleAlert className="mt-0.5 size-4 shrink-0" />
              {w}
            </p>
          ))}
        </div>
      )}

      <div className={cn("grid items-start gap-6", stats && "lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]")}>
        {stats && (
          <div className="divide-y rounded-lg border bg-card">
            <StatGroup title="Inventaris">
              <ul className="divide-y">
                <StatRow
                  label="URL's gescand"
                  value={stats.total_urls}
                  hint={scan.discovery_source === "sitemap" ? "Uit de sitemap" : "Via crawl"}
                />
                <StatRow label="Indexeerbaar" value={stats.indexable} hint={`${stats.non_indexable} niet indexeerbaar`} />
                <StatRow
                  label="Fouten (4xx/5xx)"
                  value={(stats.status["4xx"] ?? 0) + (stats.status["5xx"] ?? 0) + (stats.status.error ?? 0)}
                  tone={(stats.status["4xx"] ?? 0) + (stats.status["5xx"] ?? 0) > 0 ? "bad" : "good"}
                  hint={`${stats.redirects} redirects`}
                />
                <StatRow
                  label="HTTP/2"
                  value={pct(stats.http2_pages, stats.html_pages)}
                  hint={`Gem. scan-respons ${stats.avg_response_ms ?? "—"} ms`}
                />
                <StatRow label="Title ontbreekt" value={stats.missing_title} tone={stats.missing_title ? "bad" : "good"} />
                <StatRow
                  label="Meta description ontbreekt"
                  value={stats.missing_meta}
                  tone={stats.missing_meta ? "warn" : "good"}
                />
                <StatRow
                  label="H1 ontbreekt / meerdere"
                  value={`${stats.missing_h1} / ${stats.multiple_h1}`}
                  tone={stats.missing_h1 ? "bad" : stats.multiple_h1 ? "warn" : "good"}
                />
                <StatRow
                  label="Pagina's met kapotte links"
                  value={stats.broken_link_pages}
                  tone={stats.broken_link_pages ? "bad" : "good"}
                />
              </ul>
            </StatGroup>

            {scan.ahrefs && <AhrefsGroup data={scan.ahrefs} />}

            <StatGroup title="Core Web Vitals (mobiel)">
              {stats.cwv.measured === 0 ? (
                <p className="text-sm text-muted-foreground">Er zijn geen Core Web Vitals gemeten.</p>
              ) : (
                <ul className="divide-y">
                  <StatRow
                    label="Gemeten"
                    value={stats.cwv.measured}
                    hint={`Gem. score ${stats.cwv.avg_performance_score ?? "—"}`}
                  />
                  <StatRow label="Goed" value={stats.cwv.good} tone="good" />
                  <StatRow label="Verbeteren" value={stats.cwv.needs_improvement} tone="warn" />
                  <StatRow label="Slecht" value={stats.cwv.poor} tone="bad" />
                </ul>
              )}
            </StatGroup>

            <StatGroup title="Actiepunten">
              <ul className="divide-y">
                <StatRow label="Totaal" value={stats.issues.total} />
                <StatRow label="Hoog" value={stats.issues.by_severity.hoog ?? 0} tone="bad" />
                <StatRow label="Middel" value={stats.issues.by_severity.middel ?? 0} tone="warn" />
                <StatRow label="Laag" value={stats.issues.by_severity.laag ?? 0} />
              </ul>
            </StatGroup>
          </div>
        )}

        <div className="min-w-0 space-y-3">
          <section className="rounded-lg border bg-card">
            <h3 className="flex items-center gap-2 border-b px-4 py-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              <Bot className="size-4" /> Nulmeting-rapport (AI-agent)
            </h3>
            {scan.ai_summary ? (
              <article className="prose prose-sm max-w-none p-6 leading-7 dark:prose-invert">
                <ReactMarkdown>{scan.ai_summary}</ReactMarkdown>
              </article>
            ) : (
              <p className="px-4 py-3 text-sm text-muted-foreground">
                {scan.status === "completed"
                  ? "Er is geen AI-rapport gegenereerd (zie waarschuwingen)."
                  : "Het rapport wordt geschreven zodra de scan klaar is."}
              </p>
            )}
          </section>

          {trace?.steps && trace.steps.length > 0 && (
            <Collapsible className="group/trace rounded-lg border bg-card">
              <CollapsibleTrigger className="flex w-full items-center justify-between px-4 py-2 text-left text-sm text-muted-foreground">
                <span>
                  Agent-stappen: {trace.steps.length} tool-aanroepen · {trace.model} ·{" "}
                  {(trace.usage?.input_tokens ?? 0) + (trace.usage?.output_tokens ?? 0)} tokens
                </span>
                <ChevronDown className="size-4 transition-transform group-data-[state=open]/trace:rotate-180" />
              </CollapsibleTrigger>
              <CollapsibleContent>
                <ol className="space-y-2 border-t px-4 py-3 text-xs">
                  {trace.steps.map((step, index) => (
                    <li key={index} className="space-y-1">
                      <p>
                        <span className="font-mono font-semibold">{step.tool}</span>{" "}
                        <span className="text-muted-foreground">{JSON.stringify(step.arguments)}</span>
                      </p>
                      <p className="line-clamp-2 break-all font-mono text-muted-foreground">{step.output_preview}</p>
                    </li>
                  ))}
                </ol>
              </CollapsibleContent>
            </Collapsible>
          )}
        </div>
      </div>
    </div>
  )
}
