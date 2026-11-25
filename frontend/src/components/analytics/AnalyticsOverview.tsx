import Link from "next/link"
import { ChevronRight, GitCompareArrows, TrendingUp } from "lucide-react"

import { ANALYTICS_BASE_URL } from "@/components/analytics/analytics-nav-items"
import { CustomerKpis } from "@/components/analytics/CustomerKpis"
import { ReportList } from "@/components/analytics/ReportList"

const COMPARE_ENTRIES = [
  { modus: "trend", title: "Trend", description: "Tot vier cijfers van deze klant naast elkaar.", icon: TrendingUp },
  { modus: "scans", title: "Scan A tegen B", description: "Twee scans van deze klant, alle cijfers.", icon: GitCompareArrows },
] as const

/** Startpagina van Analytics: kerncijfers van de klant uit het adres, de rapporten en de ingang naar Vergelijken. */
export function AnalyticsOverview({ customerId }: { customerId: string }) {
  return (
    <div className="space-y-8">
      <section className="space-y-3">
        <SectionHeading title="Kerncijfers" description="Laatste nulmeting of kwartaalscan, met het verschil t.o.v. de meting ervoor." />
        {/* key: bij een andere klant (via de sidebar) begint de tegelrij opnieuw, zonder cijfers van de vorige. */}
        <CustomerKpis key={customerId} customerId={customerId} />
      </section>

      <section className="space-y-3">
        <SectionHeading title="Rapporten" description="Vaste grafiekrapporten voor deze klant." />
        <ReportList customerId={customerId} />
      </section>

      <section className="space-y-3">
        <SectionHeading title="Vergelijken" description="Over de tijd of tussen twee scans." />
        <ul className="grid gap-3 sm:grid-cols-2">
          {COMPARE_ENTRIES.map((entry) => {
            const query = new URLSearchParams({ klant: customerId })
            if (entry.modus !== "trend") query.set("modus", entry.modus)
            return (
              <li key={entry.modus}>
                <Link
                  href={`${ANALYTICS_BASE_URL}/vergelijken?${query}`}
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
