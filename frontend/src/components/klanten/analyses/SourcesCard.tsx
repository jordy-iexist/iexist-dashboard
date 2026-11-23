import {
  SOURCE_LABELS,
  SOURCE_STATE_LABELS,
  type SourceKey,
  type SourceState,
  type Sources,
} from "@/lib/competitor-analysis"
import { cn } from "@/lib/utils"

/** De bronnen in de wizard met wat ze leveren; `google` wordt niet gebruikt en staat er niet in. */
const SHOWN: { key: SourceKey; provides: string }[] = [
  { key: "prt", provides: "Rankings & doel-URL" },
  { key: "ahrefs", provides: "SERP top 10, DR en verwijzende domeinen, volume en KD" },
  { key: "pagespeed", provides: "Core Web Vitals" },
  { key: "claude", provides: "Analyse & teksten" },
]

const DOT: Record<SourceState, string> = {
  ok: "bg-green-600",
  empty: "bg-amber-500",
  not_configured: "bg-muted-foreground/50",
  skipped: "bg-muted-foreground/50",
  error: "bg-red-600",
  blocked: "bg-red-600",
}

/** Kaart "Databronnen": per bron een tegel met wat hij levert, de status en de melding. */
export function SourcesCard({ sources }: { sources: Sources }) {
  return (
    <section aria-labelledby="wizard-sources-title" className="flex flex-col gap-4 rounded-xl border bg-card px-6 py-5">
      <h2 id="wizard-sources-title" className="text-base font-semibold">
        Databronnen
      </h2>
      <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {SHOWN.map(({ key, provides }) => {
          const status = sources[key]
          const ok = status.state === "ok"
          return (
            <li key={key} className="flex flex-col gap-1.5 rounded-lg border px-4 py-3">
              <div className="flex items-start justify-between gap-2">
                <p className="text-sm font-semibold">{SOURCE_LABELS[key]}</p>
                <span className="inline-flex shrink-0 items-center gap-1.5 text-xs text-muted-foreground">
                  <span aria-hidden className={cn("size-2 rounded-full", DOT[status.state])} />
                  {SOURCE_STATE_LABELS[status.state]}
                </span>
              </div>
              <p className="text-xs text-muted-foreground">{provides}</p>
              {status.message && (
                <p
                  className={cn(
                    "text-xs",
                    ok
                      ? "text-muted-foreground"
                      : status.state === "error" || status.state === "blocked"
                        ? "text-red-700 dark:text-red-300"
                        : "text-amber-700 dark:text-amber-400"
                  )}
                >
                  {status.message}
                </p>
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}
