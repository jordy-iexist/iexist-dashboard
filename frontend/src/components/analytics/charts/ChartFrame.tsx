import { cn } from "@/lib/utils"

import type { ChartSeries } from "./types"

type ChartFrameProps = {
  title: React.ReactNode
  description?: React.ReactNode
  /** Legenda (vanaf twee reeksen); één reeks heeft genoeg aan de titel. */
  legend?: ChartSeries[]
  legendShape?: "line" | "rect"
  /** Hoogte van het tekengebied in px, inclusief de x-as. Vast, zodat er niets verspringt. */
  height: number
  /** Herladen: de vorige grafiek blijft staan, gedimd. */
  loading?: boolean
  /** Leegstaat i.p.v. de grafiek (bijv. "Nog niet gemeten"). */
  empty?: React.ReactNode
  footer?: React.ReactNode
  className?: string
  children?: React.ReactNode
}

/** Kaart rond één grafiek: titel, legenda, vaste hoogte, laad- en leegstaat. Importeert geen Recharts. */
export function ChartFrame({
  title,
  description,
  legend,
  legendShape = "line",
  height,
  loading = false,
  empty,
  footer,
  className,
  children,
}: ChartFrameProps) {
  return (
    <figure className={cn("min-w-0 space-y-3 rounded-lg border bg-card p-4 shadow-xs", className)} aria-busy={loading}>
      <figcaption className="space-y-1">
        <p className="text-sm font-semibold">{title}</p>
        {description && <p className="text-xs text-muted-foreground">{description}</p>}
      </figcaption>
      {legend && legend.length > 1 && !empty && <ChartLegend series={legend} shape={legendShape} />}
      <div className={cn("relative transition-opacity", loading && "opacity-50")} style={{ height }}>
        {empty ? (
          <div className="flex h-full items-center justify-center rounded-md bg-muted/40 px-4 text-center text-sm text-muted-foreground">
            {empty}
          </div>
        ) : (
          children
        )}
      </div>
      {footer}
    </figure>
  )
}

export function ChartLegend({ series, shape = "line" }: { series: ChartSeries[]; shape?: "line" | "rect" }) {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
      {series.map((s) => (
        <li key={s.key} className="flex items-center gap-1.5">
          <span
            aria-hidden
            className={shape === "line" ? "h-0.5 w-3.5 rounded-full" : "size-2.5 rounded-[2px]"}
            style={{ backgroundColor: s.color }}
          />
          {s.label}
        </li>
      ))}
    </ul>
  )
}

/** Plaatshouder met dezelfde hoogte terwijl de grafiekcode laadt (geen verspringing). */
export function ChartPlaceholder() {
  return <div className="h-full w-full animate-pulse rounded-md bg-muted/40" aria-hidden />
}
