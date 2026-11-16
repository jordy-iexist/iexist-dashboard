import { ArrowDown, ArrowUp, Minus } from "lucide-react"

import type { MetricUnit } from "@/lib/analytics/api"
import { deltaTone, formatDelta } from "@/lib/analytics/format"
import { cn } from "@/lib/utils"

/**
 * Verschil met pijl, teken en (alleen bij een richting) groen/rood. Kleur nooit
 * alleen: de pijl en het teken dragen de richting, de schermlezertekst het oordeel.
 */
export function MetricDelta({
  delta,
  unit,
  higherIsBetter,
  className,
}: {
  delta: number | null
  unit: MetricUnit
  higherIsBetter: boolean | null
  className?: string
}) {
  if (delta == null) return <span className={cn("text-muted-foreground", className)}>–</span>
  const tone = deltaTone(delta, higherIsBetter)
  const Icon = delta > 0 ? ArrowUp : delta < 0 ? ArrowDown : Minus
  const verdict = tone === "good" ? "verbetering" : tone === "bad" ? "verslechtering" : null
  return (
    <span
      className={cn(
        "inline-flex items-center gap-0.5 whitespace-nowrap font-medium tabular-nums",
        tone === "good" && "text-green-700 dark:text-green-400",
        tone === "bad" && "text-red-700 dark:text-red-400",
        tone === "neutral" && "text-muted-foreground",
        className
      )}
    >
      <Icon className="size-3 shrink-0" aria-hidden />
      {formatDelta(delta, unit)}
      {verdict && <span className="sr-only"> ({verdict})</span>}
    </span>
  )
}
