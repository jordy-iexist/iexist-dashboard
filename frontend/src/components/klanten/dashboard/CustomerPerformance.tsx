import { ContentGapsCard } from "@/components/klanten/dashboard/ContentGapsCard"
import { KpiCard, type KpiTone } from "@/components/klanten/dashboard/KpiCard"
import { QuickWinsCard } from "@/components/klanten/dashboard/QuickWinsCard"
import { RecentAnalysesCard } from "@/components/klanten/dashboard/RecentAnalysesCard"
import { formatDecimal, roundTo, TrendArrow } from "@/components/klanten/dashboard/trend"
import {
  fetchCustomerImprovements,
  fetchCustomerQuickWins,
  fetchCustomerRankings,
} from "@/lib/customer-api"
import type { CustomerImprovements, CustomerQuickWins } from "@/lib/customer-types"

type Hint = { hint: React.ReactNode; tone: KpiTone }

/** Regel "↑ n t.o.v. vorige maand"; positief = verbeterd. */
function monthHint(delta: number | null, digits: number): Hint {
  if (delta == null) return { hint: "geen vergelijking", tone: "muted" }
  const rounded = roundTo(delta, digits)
  if (rounded === 0) return { hint: "gelijk aan vorige maand", tone: "muted" }
  return {
    hint: (
      <>
        <TrendArrow value={rounded} digits={digits} /> t.o.v. vorige maand
      </>
    ),
    tone: rounded > 0 ? "good" : "bad",
  }
}

function improvementsCard(customerId: string, improvements: CustomerImprovements | null) {
  const href = `/dashboard/livegang/seo-geo/${customerId}?fase=aanpassingen`
  if (!improvements || !improvements.hasSources) {
    return <KpiCard label="Open verbeterpunten" value="—" hint="nog geen scan" href={href} />
  }
  const { open, openHigh } = improvements
  return (
    <KpiCard
      label="Open verbeterpunten"
      value={open.toLocaleString("nl-NL")}
      hint={openHigh > 0 ? `${openHigh} met hoge prioriteit` : "geen met hoge prioriteit"}
      tone={openHigh > 0 ? "warn" : "muted"}
      href={href}
    />
  )
}

function quickWinsValue(quickWins: CustomerQuickWins) {
  if (quickWins.state !== "ok") return "—"
  if (quickWins.capped) return `${quickWins.limit}+`
  return quickWins.rows.length.toLocaleString("nl-NL")
}

// KPI-rij, Quick wins-card en de twee cards eronder; staat in een Suspense omdat Pro Rank
// Tracker live wordt bevraagd en Ahrefs bij een verouderde stand opnieuw wordt opgehaald.
export async function CustomerPerformance({
  customerId,
  customerName,
}: {
  customerId: string
  customerName: string
}) {
  const [rankings, quickWins, improvements] = await Promise.all([
    fetchCustomerRankings(customerId),
    fetchCustomerQuickWins(customerId),
    fetchCustomerImprovements(customerId),
  ])

  const ok = rankings.state === "ok"
  const notTracked =
    rankings.state === "not_tracked" ? "niet gevolgd in Pro Rank Tracker" : undefined
  const avg = ok ? monthHint(rankings.avg_position_delta, 1) : null
  const top3 = ok ? monthHint(rankings.top3_delta, 0) : null
  const quickWinsOk = quickWins.state === "ok"

  return (
    <>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          label={ok ? `Gem. positie (${rankings.ranked} zoekwoorden)` : "Gem. positie"}
          value={ok && rankings.avg_position != null ? formatDecimal(rankings.avg_position, 1) : "—"}
          hint={avg?.hint ?? notTracked}
          tone={avg?.tone}
        />
        <KpiCard
          label="Zoekwoorden in top 3"
          value={ok ? String(rankings.top3) : "—"}
          hint={top3?.hint ?? notTracked}
          tone={top3?.tone}
        />
        <KpiCard
          label="Quick wins (positie 4–20)"
          value={quickWinsValue(quickWins)}
          hint={quickWinsOk ? "kansrijk om te optimaliseren" : undefined}
          tone="accent"
        />
        {improvementsCard(customerId, improvements)}
      </div>

      <QuickWinsCard quickWins={quickWins} />

      <div className="grid gap-4 lg:grid-cols-2">
        <RecentAnalysesCard />
        <ContentGapsCard rankings={rankings} customerName={customerName} />
      </div>
    </>
  )
}
