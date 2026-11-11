"use client"

import ReactMarkdown from "react-markdown"
import { Bot, ChevronDown, TriangleAlert } from "lucide-react"

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { CompactStat, StatGrid } from "@/components/livegang/shared"
import type { LaunchScanDetail } from "@/lib/launch-checklist"

function pct(part: number, total: number) {
  return total > 0 ? `${Math.round((part / total) * 100)}%` : "—"
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

      {stats && (
        <>
          <section className="space-y-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Inventaris</h3>
            <StatGrid className="grid-cols-2 sm:grid-cols-4 xl:grid-cols-8">
              <CompactStat
                label="URL's gescand"
                value={stats.total_urls}
                hint={scan.discovery_source === "sitemap" ? "Uit de sitemap" : "Via crawl"}
              />
              <CompactStat label="Indexeerbaar" value={stats.indexable} hint={`${stats.non_indexable} niet indexeerbaar`} />
              <CompactStat
                label="Fouten (4xx/5xx)"
                value={(stats.status["4xx"] ?? 0) + (stats.status["5xx"] ?? 0) + (stats.status.error ?? 0)}
                tone={(stats.status["4xx"] ?? 0) + (stats.status["5xx"] ?? 0) > 0 ? "bad" : "good"}
                hint={`${stats.redirects} redirects`}
              />
              <CompactStat
                label="HTTP/2"
                value={pct(stats.http2_pages, stats.html_pages)}
                hint={`Gem. scan-respons ${stats.avg_response_ms ?? "—"} ms`}
              />
              <CompactStat label="Title ontbreekt" value={stats.missing_title} tone={stats.missing_title ? "bad" : "good"} />
              <CompactStat label="Meta description ontbreekt" value={stats.missing_meta} tone={stats.missing_meta ? "warn" : "good"} />
              <CompactStat
                label="H1 ontbreekt / meerdere"
                value={`${stats.missing_h1} / ${stats.multiple_h1}`}
                tone={stats.missing_h1 ? "bad" : stats.multiple_h1 ? "warn" : "good"}
              />
              <CompactStat
                label="Pagina's met kapotte links"
                value={stats.broken_link_pages}
                tone={stats.broken_link_pages ? "bad" : "good"}
              />
            </StatGrid>
          </section>

          <div className="grid gap-6 lg:grid-cols-2">
            <section className="space-y-2">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Core Web Vitals (mobiel)
              </h3>
              {stats.cwv.measured === 0 ? (
                <p className="text-sm text-muted-foreground">Er zijn geen Core Web Vitals gemeten.</p>
              ) : (
                <StatGrid className="grid-cols-2 sm:grid-cols-4">
                  <CompactStat
                    label="Gemeten"
                    value={stats.cwv.measured}
                    hint={`Gem. score ${stats.cwv.avg_performance_score ?? "—"}`}
                  />
                  <CompactStat label="Goed" value={stats.cwv.good} tone="good" />
                  <CompactStat label="Verbeteren" value={stats.cwv.needs_improvement} tone="warn" />
                  <CompactStat label="Slecht" value={stats.cwv.poor} tone="bad" />
                </StatGrid>
              )}
            </section>

            <section className="space-y-2">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Actiepunten</h3>
              <StatGrid className="grid-cols-2 sm:grid-cols-4">
                <CompactStat label="Totaal" value={stats.issues.total} />
                <CompactStat label="Hoog" value={stats.issues.by_severity.hoog ?? 0} tone="bad" />
                <CompactStat label="Middel" value={stats.issues.by_severity.middel ?? 0} tone="warn" />
                <CompactStat label="Laag" value={stats.issues.by_severity.laag ?? 0} />
              </StatGrid>
            </section>
          </div>
        </>
      )}

      <section className="space-y-3">
        <h3 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          <Bot className="size-4" /> Nulmeting-rapport (AI-agent)
        </h3>
        {scan.ai_summary ? (
          <article className="prose prose-sm max-w-none rounded-lg border bg-card p-6 leading-7 dark:prose-invert">
            <ReactMarkdown>{scan.ai_summary}</ReactMarkdown>
          </article>
        ) : (
          <p className="text-sm text-muted-foreground">
            {scan.status === "completed"
              ? "Er is geen AI-rapport gegenereerd (zie waarschuwingen)."
              : "Het rapport wordt geschreven zodra de scan klaar is."}
          </p>
        )}

        {trace?.steps && trace.steps.length > 0 && (
          <Collapsible className="group/trace rounded-lg border">
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
      </section>
    </div>
  )
}
