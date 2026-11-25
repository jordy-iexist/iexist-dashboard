import { formatInt } from "@/components/klanten/analyses/result-parts"
import { KpiCard } from "@/components/klanten/dashboard/KpiCard"
import type { Kpis, OverlapBasis } from "@/lib/keyword-competitors"

const DASH = "–"

/** Geheel getal in Nederlandse notatie; onbekend "–". */
export function formatCount(value: number | null | undefined) {
  return value == null ? DASH : formatInt(value)
}

/** Getal met hooguit één decimaal ("4,5"); onbekend "–". */
export function formatDecimal(value: number | null | undefined) {
  return value == null ? DASH : value.toLocaleString("nl-NL", { maximumFractionDigits: 1 })
}

/** Percentage zonder decimalen ("42%"); onbekend "–". */
export function formatPct(value: number | null | undefined) {
  return value == null ? DASH : `${Math.round(value).toLocaleString("nl-NL")}%`
}

function TrafficChange({ pct }: { pct: number }) {
  const rounded = Math.round(pct)
  if (rounded === 0) return <span className="text-muted-foreground">± 0%</span>
  const up = rounded > 0
  return (
    <span className={up ? "text-green-700 dark:text-green-400" : "text-red-700 dark:text-red-400"}>
      <span aria-hidden="true">{up ? "↑" : "↓"}</span>
      <span className="sr-only">{up ? "gestegen met" : "gedaald met"}</span> {Math.abs(rounded).toLocaleString("nl-NL")}%
    </span>
  )
}

/** De vier KPI-kaarten boven de tabel. Zonder momentopname (`kpis` null) overal "–". */
export function CompetitorKpis({
  kpis,
  customerName,
  overlapBasis,
  trackedSample,
}: {
  kpis: Kpis | null
  customerName: string
  overlapBasis: OverlapBasis
  trackedSample: number
}) {
  const keywords = kpis?.organic_keywords
  const traffic = kpis?.organic_traffic
  const rating = kpis?.domain_rating
  const overlap = kpis?.top5_overlap

  const belowMedian =
    rating?.value != null && rating.competitor_median != null && rating.value < rating.competitor_median

  const overlapHint =
    overlap?.shared_avg == null
      ? null
      : overlapBasis === "tracked"
        ? `gemiddeld in ${formatDecimal(overlap.shared_avg)} van ${formatCount(trackedSample)} zoekresultaten`
        : `gemiddeld ${formatDecimal(overlap.shared_avg)} gedeelde zoekwoorden`

  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <KpiCard
        label={`Organische zoekwoorden ${customerName}`}
        value={formatCount(keywords?.value)}
        hint={keywords?.top10 != null ? `${formatCount(keywords.top10)} in de top 10` : null}
      />
      <KpiCard
        label="Organisch verkeer"
        value={traffic?.value != null ? `${formatCount(traffic.value)} /mnd` : DASH}
        hint={
          <>
            <span>schatting Ahrefs</span>
            {traffic?.change_pct != null && (
              <>
                {" · "}
                <TrafficChange pct={traffic.change_pct} />
              </>
            )}
          </>
        }
      />
      <KpiCard
        label="Domain Rating"
        value={formatCount(rating?.value)}
        tone={belowMedian ? "warn" : "muted"}
        hint={
          rating?.competitor_median != null ? (
            <span title={belowMedian ? "Lager dan de mediaan van de concurrenten" : undefined}>
              mediaan concurrenten: {formatDecimal(rating.competitor_median)}
            </span>
          ) : null
        }
      />
      <KpiCard
        label="Overlap met top 5"
        value={formatPct(overlap?.pct)}
        hint={overlapHint}
      />
    </div>
  )
}
