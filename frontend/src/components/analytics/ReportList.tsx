import Link from "next/link"
import { ChevronRight } from "lucide-react"

import { ANALYTICS_BASE_URL } from "@/components/analytics/analytics-nav-items"
import { Pill } from "@/components/livegang/shared"
import { REPORTS, phasesLabel } from "@/lib/analytics/reports"

/** Rapportkaarten; een gekozen klant (`?klant=`) gaat mee naar het rapport. */
export function ReportList({ customerId }: { customerId?: string | null }) {
  const query = customerId ? `?klant=${encodeURIComponent(customerId)}` : ""
  return (
    <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {REPORTS.map((report) => (
        <li key={report.slug}>
          <Link
            href={`${ANALYTICS_BASE_URL}/rapporten/${report.slug}${query}`}
            className="group flex h-full items-start gap-3 rounded-lg border bg-card p-4 shadow-xs transition-colors hover:bg-muted/50"
          >
            <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-foreground">
              <report.icon className="size-4" />
            </span>
            <span className="min-w-0 flex-1 space-y-1">
              <span className="flex items-center gap-2">
                <span className="font-semibold">{report.title}</span>
                <ChevronRight className="ml-auto size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
              </span>
              <span className="block text-sm text-muted-foreground">{report.description}</span>
              <span className="block pt-1">
                <Pill>Uit {phasesLabel(report.phases)}</Pill>
              </span>
            </span>
          </Link>
        </li>
      ))}
    </ul>
  )
}
