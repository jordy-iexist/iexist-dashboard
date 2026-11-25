import Link from "next/link"

import { PERIOD_DAYS, searchConsoleHref, type PeriodDays } from "@/lib/search-console-insights"
import { cn } from "@/lib/utils"

/** Drie links voor de periode (7 / 28 / 90 dagen); 28 dagen is het adres zonder querystring. */
export function PeriodPicker({ customerId, days }: { customerId: string; days: PeriodDays }) {
  return (
    <nav aria-label="Periode" className="inline-flex items-center gap-0.5 rounded-full border bg-card p-0.5">
      {PERIOD_DAYS.map((option) => {
        const active = option === days
        return (
          <Link
            key={option}
            href={searchConsoleHref(customerId, option)}
            prefetch={false}
            aria-current={active ? "page" : undefined}
            className={cn(
              "inline-flex h-8 items-center rounded-full px-3 text-sm font-medium whitespace-nowrap transition-colors focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none",
              active
                ? "bg-foreground text-background"
                : "text-muted-foreground hover:bg-muted hover:text-foreground"
            )}
          >
            {option} dagen
          </Link>
        )
      })}
    </nav>
  )
}
