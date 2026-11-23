import { ArrowDown, ArrowUp } from "lucide-react"

/** Rondt af op `digits` decimalen; -0 wordt 0. */
export function roundTo(value: number, digits: number) {
  const factor = 10 ** digits
  return Math.round(value * factor) / factor || 0
}

export function formatDecimal(value: number, digits: number) {
  return value.toLocaleString("nl-NL", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

/** Pijl plus absoluut verschil, zoals in `RankingsSection`; kleur zet de ouder. */
export function TrendArrow({ value, digits = 0 }: { value: number; digits?: number }) {
  const Icon = value > 0 ? ArrowUp : ArrowDown
  return (
    <span className="inline-flex items-center gap-0.5">
      <Icon className="size-3 shrink-0" aria-hidden="true" />
      <span className="sr-only">{value > 0 ? "gestegen" : "gedaald"} met </span>
      {formatDecimal(Math.abs(value), digits)}
    </span>
  )
}
