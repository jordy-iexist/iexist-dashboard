"use client"

import { Check, Loader2, Square } from "lucide-react"

import { CompactStat, ProgressBar, StatGrid } from "@/components/livegang/shared"
import { Button } from "@/components/ui/button"
import { ANALYSIS_STATUS_LABELS, ANALYSIS_STEPS, type AnalysisDetail } from "@/lib/competitor-analysis"
import { cn } from "@/lib/utils"

/** Waarde en maximum van de voortgangsbalk voor de huidige stap. */
function barFor(analysis: AnalysisDetail): { value: number; max: number; detail: string | null } {
  switch (analysis.status) {
    case "fetching":
      return {
        value: analysis.fetched_pages,
        max: analysis.total_pages,
        detail: analysis.total_pages ? `${analysis.fetched_pages} / ${analysis.total_pages} pagina's` : null,
      }
    case "analyzing":
    case "serp":
      return {
        value: analysis.done_keywords,
        max: analysis.total_keywords,
        detail: `${analysis.done_keywords} / ${analysis.total_keywords} zoekwoorden`,
      }
    default:
      return { value: 0, max: 0, detail: null }
  }
}

/** Voortgang van een lopende analyse: status, stappen, balk, tellers en "Annuleren". */
export function AnalysisProgress({
  analysis,
  canceling,
  onCancel,
}: {
  analysis: AnalysisDetail
  canceling: boolean
  onCancel: () => void
}) {
  const currentIndex = ANALYSIS_STEPS.indexOf(analysis.status)
  const bar = barFor(analysis)
  const showVitals = analysis.modules.includes("tech") && analysis.vitals_total > 0

  return (
    <section aria-label="Voortgang van de analyse" className="space-y-4 rounded-xl border bg-card px-6 py-5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <p role="status" className="flex items-center gap-2 text-sm font-semibold">
          <Loader2 className="size-4 animate-spin text-primary" aria-hidden="true" />
          {ANALYSIS_STATUS_LABELS[analysis.status]}
          {bar.detail && <span className="font-normal text-muted-foreground">· {bar.detail}</span>}
        </p>
        <Button size="sm" variant="ghost" className="ml-auto" onClick={onCancel} disabled={canceling}>
          {canceling ? <Loader2 className="animate-spin" /> : <Square />}
          Annuleren
        </Button>
      </div>

      <ProgressBar value={bar.value} max={bar.max} />

      <ol className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted-foreground" aria-label="Stappen">
        {ANALYSIS_STEPS.map((step, index) => {
          const done = currentIndex > index
          const current = currentIndex === index
          return (
            <li
              key={step}
              aria-current={current ? "step" : undefined}
              className={cn(
                "flex items-center gap-1",
                done && "text-green-700 dark:text-green-400",
                current && "font-semibold text-foreground"
              )}
            >
              {done ? <Check className="size-3" aria-hidden="true" /> : <span aria-hidden="true">{index + 1}.</span>}
              {ANALYSIS_STATUS_LABELS[step]}
              {done && <span className="sr-only"> (klaar)</span>}
            </li>
          )
        })}
      </ol>

      <StatGrid className={cn("grid-cols-2", showVitals ? "sm:grid-cols-3" : "sm:grid-cols-2")}>
        <CompactStat label="Zoekwoorden" value={`${analysis.done_keywords}/${analysis.total_keywords}`} hint="klaar" />
        <CompactStat
          label="Pagina's"
          value={`${analysis.fetched_pages}/${analysis.total_pages}`}
          hint={analysis.failed_pages ? `${analysis.failed_pages} niet opgehaald` : "opgehaald"}
          tone={analysis.failed_pages ? "warn" : undefined}
        />
        {showVitals && (
          <CompactStat label="PageSpeed" value={`${analysis.vitals_measured}/${analysis.vitals_total}`} hint="LCP gemeten" />
        )}
      </StatGrid>
    </section>
  )
}
