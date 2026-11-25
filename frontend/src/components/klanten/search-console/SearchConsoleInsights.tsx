import { formatInt, ResultCard } from "@/components/klanten/analyses/result-parts"
import { KpiCard, type KpiTone } from "@/components/klanten/dashboard/KpiCard"
import { roundTo, TrendArrow } from "@/components/klanten/dashboard/trend"
import { DecliningPagesCard } from "@/components/klanten/search-console/DecliningPagesCard"
import { formatCtr, formatPosition } from "@/components/klanten/search-console/format"
import { OpportunitiesTable } from "@/components/klanten/search-console/OpportunitiesTable"
import { SearchConsoleNotice } from "@/components/klanten/search-console/SearchConsoleNotice"
import { UntrackedQueriesCard } from "@/components/klanten/search-console/UntrackedQueriesCard"
import { fetchCustomerSearchConsoleInsights } from "@/lib/customer-api"
import type {
  InsightsTotals,
  OpportunitiesSection,
  PeriodDays,
} from "@/lib/search-console-insights"

type Hint = { hint: React.ReactNode; tone: KpiTone }

const NO_COMPARISON: Hint = { hint: "geen vergelijking", tone: "muted" }

/** Regel onder een KPI: `delta` positief = verbeterd (groen, pijl omhoog). */
function trendHint(delta: number, digits: number, suffix: React.ReactNode): Hint {
  const rounded = roundTo(delta, digits)
  if (rounded === 0) return { hint: "gelijk aan vorige periode", tone: "muted" }
  return {
    hint: (
      <>
        <TrendArrow value={rounded} digits={digits} />
        {suffix}
      </>
    ),
    tone: rounded > 0 ? "good" : "bad",
  }
}

/** Klikken en vertoningen: procentuele verandering; zonder vorige waarde geen vergelijking. */
function percentHint(now: number, previous: number | null): Hint {
  if (previous == null || previous <= 0) return NO_COMPARISON
  return trendHint(((now - previous) / previous) * 100, 0, "% t.o.v. vorige periode")
}

function kpiHints(totals: InsightsTotals, previous: InsightsTotals | null) {
  // Zonder vorige data of zonder vorige vertoningen valt er niets te vergelijken.
  const prev = previous && previous.impressions > 0 ? previous : null
  return {
    clicks: percentHint(totals.clicks, prev?.clicks ?? null),
    impressions: percentHint(totals.impressions, prev?.impressions ?? null),
    ctr: prev ? trendHint((totals.ctr - prev.ctr) * 100, 1, " procentpunt") : NO_COMPARISON,
    // Lagere positie is beter: vorige − nu, positief = verbeterd.
    position:
      prev && prev.position != null && totals.position != null
        ? trendHint(prev.position - totals.position, 1, " posities")
        : NO_COMPARISON,
  }
}

function OpportunitiesCard({
  customerId,
  section,
}: {
  customerId: string
  section: OpportunitiesSection
}) {
  const ok = section.state === "ok"
  const extraLines = ok && (section.brand_excluded > 0 || section.truncated || section.total > section.rows.length)

  return (
    <ResultCard
      id="ctr-kansen"
      title="CTR-kansen – veel vertoningen, weinig klikken"
      description={
        <>
          CTR vergeleken met wat gebruikelijk is voor die positie. Vaak op te lossen met een betere
          title en meta description – snelste winst. De cijfers zijn per zoekterm en pagina gerekend
          en tellen daardoor niet op tot de totalen hierboven.
        </>
      }
    >
      {!ok ? (
        <p className="rounded-lg border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
          {section.message || "De CTR-kansen konden niet worden opgehaald uit Search Console."}
        </p>
      ) : section.rows.length === 0 ? (
        <p className="rounded-lg border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
          Geen CTR-kansen gevonden bij deze drempel
          {section.min_impressions > 0 && ` (minimaal ${formatInt(section.min_impressions)} vertoningen)`}.
        </p>
      ) : (
        <OpportunitiesTable
          customerId={customerId}
          rows={section.rows}
          potentialClicksPerMonth={section.potential_clicks_per_month}
        />
      )}

      {extraLines && (
        <div className="space-y-0.5 text-xs text-muted-foreground">
          {section.total > section.rows.length && (
            <p>
              De {formatInt(section.rows.length)} grootste van {formatInt(section.total)} kansen; het
              potentieel telt alle kansen mee.
            </p>
          )}
          {section.brand_excluded > 0 && (
            <p>
              {formatInt(section.brand_excluded)}{" "}
              {section.brand_excluded === 1 ? "merkzoekterm" : "merkzoektermen"} niet meegeteld.
            </p>
          )}
          {section.truncated && (
            <p>
              Google leverde niet alle zoektermen: de lijst is afgekapt, dus kansen met weinig
              vertoningen kunnen ontbreken.
            </p>
          )}
        </div>
      )}
    </ResultCard>
  )
}

// Inhoud van het scherm: bij een andere toestand dan "ok" één melding, anders de KPI's, de
// CTR-kansen en de twee kaarten eronder. Staat in een Suspense omdat Search Console live wordt
// bevraagd (de eerste keer enkele seconden).
export async function SearchConsoleInsights({
  customerId,
  days,
}: {
  customerId: string
  days: PeriodDays
}) {
  const insights = await fetchCustomerSearchConsoleInsights(customerId, days)

  if (insights.state !== "ok" || !insights.totals) {
    return (
      <SearchConsoleNotice
        state={insights.state === "ok" ? "error" : insights.state}
        message={insights.message}
        customerId={customerId}
      />
    )
  }

  const { totals } = insights
  const hints = kpiHints(totals, insights.totals_previous)

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard label="Klikken" value={formatInt(totals.clicks)} {...hints.clicks} />
        <KpiCard label="Vertoningen" value={formatInt(totals.impressions)} {...hints.impressions} />
        <KpiCard label="Gemiddelde CTR" value={formatCtr(totals.ctr)} {...hints.ctr} />
        <KpiCard
          label="Gemiddelde positie"
          value={totals.position == null ? "—" : formatPosition(totals.position)}
          {...hints.position}
        />
      </div>

      <OpportunitiesCard customerId={customerId} section={insights.opportunities} />

      <div className="grid gap-4 lg:grid-cols-2">
        <UntrackedQueriesCard section={insights.untracked} />
        <DecliningPagesCard section={insights.declining} />
      </div>
    </div>
  )
}
