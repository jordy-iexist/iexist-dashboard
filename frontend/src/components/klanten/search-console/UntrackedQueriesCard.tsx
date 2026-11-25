import { formatInt, ResultCard } from "@/components/klanten/analyses/result-parts"
import { formatPosition } from "@/components/klanten/search-console/format"
import { Pill } from "@/components/livegang/shared"
import type { UntrackedSection } from "@/lib/search-console-insights"

const emptyClass =
  "rounded-lg border border-dashed px-4 py-6 text-center text-sm text-muted-foreground"

/** Melding bij een toestand zonder (betrouwbare) vergelijking met Pro Rank Tracker. */
function stateMessage(section: UntrackedSection): string | null {
  switch (section.state) {
    case "ok":
      return null
    case "prt_not_tracked":
      return "Deze site wordt nog niet gevolgd in Pro Rank Tracker. Hieronder de zoektermen met de meeste vertoningen."
    case "prt_not_configured":
      return section.message || "De koppeling met Pro Rank Tracker is niet ingesteld, dus er is niets om mee te vergelijken."
    case "prt_error":
      return section.message || "De gevolgde zoekwoorden konden niet worden opgehaald uit Pro Rank Tracker."
    case "unavailable":
      return section.message || "De zoektermen konden niet worden opgehaald uit Search Console."
  }
}

// Zoektermen met vertoningen in Search Console die niet in Pro Rank Tracker staan.
export function UntrackedQueriesCard({ section }: { section: UntrackedSection }) {
  const showRows = section.state === "ok" || section.state === "prt_not_tracked"
  const notice = stateMessage(section)
  const more = showRows ? section.total - section.rows.length : 0

  return (
    <ResultCard
      id="niet-gevolgd"
      title="Zoektermen die je nog niet volgt"
      description="Vertoningen in Search Console, maar niet in Pro Rank Tracker."
    >
      {notice &&
        (showRows ? (
          <p className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-[13px] text-amber-900 dark:bg-amber-900/20 dark:text-amber-200">
            {notice}
          </p>
        ) : (
          <p className={emptyClass}>{notice}</p>
        ))}

      {showRows &&
        (section.rows.length === 0 ? (
          <p className={emptyClass}>
            {section.state === "ok"
              ? "Alle zoektermen met genoeg vertoningen worden al gevolgd in Pro Rank Tracker."
              : "Geen zoektermen met genoeg vertoningen gevonden."}
          </p>
        ) : (
          <ul>
            {section.rows.map((row) => (
              <li key={row.query} className="flex items-center gap-3 border-b py-2.5">
                <div className="min-w-0 flex-1 space-y-0.5">
                  <p className="text-sm font-semibold break-words">{row.query}</p>
                  <p className="text-xs text-muted-foreground tabular-nums">
                    {formatInt(row.impressions)} vertoningen · positie {formatPosition(row.position)}
                  </p>
                </div>
                <span
                  aria-disabled="true"
                  title="Binnenkort"
                  className="cursor-not-allowed text-[13px] font-semibold whitespace-nowrap text-muted-foreground"
                >
                  + Volgen
                </span>
              </li>
            ))}
          </ul>
        ))}

      {showRows && section.rows.length > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
          <span>
            {more > 0
              ? `En nog ${formatInt(more)} ${more === 1 ? "zoekterm" : "zoektermen"}.`
              : section.state === "ok" && section.tracked_keywords > 0
                ? `${formatInt(section.tracked_keywords)} zoekwoorden gevolgd in Pro Rank Tracker.`
                : null}
          </span>
          <span className="inline-flex items-center gap-1.5">
            Volgen vanuit dit scherm <Pill>Binnenkort</Pill>
          </span>
        </div>
      )}
    </ResultCard>
  )
}
