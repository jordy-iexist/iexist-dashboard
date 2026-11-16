import Link from "next/link"
import { ChevronRight, GitCompareArrows, TrendingUp, Users } from "lucide-react"

import { ANALYTICS_BASE_URL } from "@/components/analytics/analytics-nav-items"
import { OverviewKpis } from "@/components/analytics/OverviewKpis"
import { ReportList } from "@/components/analytics/ReportList"

const COMPARE_ENTRIES = [
  { modus: "trend", title: "Trend per klant", description: "Tot vier cijfers van één klant naast elkaar.", icon: TrendingUp, keepCustomer: true },
  { modus: "scans", title: "Scan A tegen B", description: "Twee scans van één klant, alle cijfers.", icon: GitCompareArrows, keepCustomer: true },
  { modus: "klanten", title: "Klanten onderling", description: "Alle klanten op één cijfer, met mediaan.", icon: Users, keepCustomer: false },
] as const

/** Startpagina van Analytics: kerncijfers over alle klanten, de rapporten en de ingang naar Vergelijken. */
export function AnalyticsOverview({ customerId }: { customerId: string | null }) {
  return (
    <div className="space-y-8">
      <section className="space-y-3">
        <SectionHeading title="Alle klanten" description="Laatste nulmeting of kwartaalscan per klant." />
        <OverviewKpis />
      </section>

      <section className="space-y-3">
        <SectionHeading title="Rapporten" description="Vaste grafiekrapporten per klant." />
        <ReportList customerId={customerId} />
      </section>

      <section className="space-y-3">
        <SectionHeading title="Vergelijken" description="Over de tijd, tussen twee scans of tussen klanten." />
        <ul className="grid gap-3 sm:grid-cols-3">
          {COMPARE_ENTRIES.map((entry) => {
            const query = new URLSearchParams()
            if (entry.modus !== "trend") query.set("modus", entry.modus)
            if (entry.keepCustomer && customerId) query.set("klant", customerId)
            const qs = query.toString()
            return (
              <li key={entry.modus}>
                <Link
                  href={`${ANALYTICS_BASE_URL}/vergelijken${qs ? `?${qs}` : ""}`}
                  className="group flex h-full items-start gap-3 rounded-lg border bg-card p-4 shadow-xs transition-colors hover:bg-muted/50"
                >
                  <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-foreground">
                    <entry.icon className="size-4" />
                  </span>
                  <span className="min-w-0 flex-1 space-y-1">
                    <span className="flex items-center gap-2">
                      <span className="font-semibold">{entry.title}</span>
                      <ChevronRight className="ml-auto size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
                    </span>
                    <span className="block text-sm text-muted-foreground">{entry.description}</span>
                  </span>
                </Link>
              </li>
            )
          })}
        </ul>
      </section>
    </div>
  )
}

function SectionHeading({ title, description }: { title: string; description: string }) {
  return (
    <div className="space-y-0.5">
      <h2 className="text-lg font-bold tracking-wide">{title}</h2>
      <p className="text-sm text-muted-foreground">{description}</p>
    </div>
  )
}
