import Link from "next/link"
import { ChevronLeft, ChevronRight } from "lucide-react"

import { maandrapportHref, monthLabel } from "@/lib/monthly-report"
import { cn } from "@/lib/utils"

const stepClass =
  "inline-flex size-8 items-center justify-center rounded-full transition-colors focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"

function Step({
  customerId,
  month,
  label,
  children,
}: {
  customerId: string
  /** null = uitgeschakeld (lopende maand of de oudste maand). */
  month: string | null
  label: string
  children: React.ReactNode
}) {
  if (!month) {
    return (
      <span aria-disabled="true" title={label} className={cn(stepClass, "text-muted-foreground/40")}>
        {children}
        <span className="sr-only">{label} (niet beschikbaar)</span>
      </span>
    )
  }
  return (
    <Link
      href={maandrapportHref(customerId, month)}
      prefetch={false}
      aria-label={`${label}: ${monthLabel(month)}`}
      title={monthLabel(month)}
      className={cn(stepClass, "text-muted-foreground hover:bg-muted hover:text-foreground")}
    >
      {children}
    </Link>
  )
}

/** Vorige/volgende maand als link met `?maand=`; de gekozen maand in het midden. */
export function MonthPicker({
  customerId,
  month,
  previousMonth,
  nextMonth,
}: {
  customerId: string
  month: string
  previousMonth: string | null
  nextMonth: string | null
}) {
  return (
    <nav aria-label="Maand" className="inline-flex items-center gap-0.5 rounded-full border bg-card p-0.5">
      <Step customerId={customerId} month={previousMonth} label="Vorige maand">
        <ChevronLeft className="size-4" aria-hidden="true" />
      </Step>
      <span className="min-w-32 px-2 text-center text-sm font-medium whitespace-nowrap">
        {monthLabel(month)}
      </span>
      <Step customerId={customerId} month={nextMonth} label="Volgende maand">
        <ChevronRight className="size-4" aria-hidden="true" />
      </Step>
    </nav>
  )
}
