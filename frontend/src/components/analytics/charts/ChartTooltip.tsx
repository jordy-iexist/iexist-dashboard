"use client"

import type { TooltipContentProps } from "recharts"

import type { ValueFormatter } from "./types"

type ChartTooltipProps = Partial<Pick<TooltipContentProps, "active" | "payload">> & {
  formatValue: ValueFormatter
  /** `line`: kort lijnstukje als sleutel; `rect`: blokje (staven). */
  keyShape?: "line" | "rect"
  /** Titel boven de regels; standaard `xLabel` van het punt. */
  title?: (datum: Record<string, unknown>) => string
}

/**
 * Tooltip voor alle grafieken: waarde vooraan en vet, reeksnaam erachter.
 * Toont elke reeks op dat punt; niet-gemeten waarden staan er als "niet gemeten".
 */
export function ChartTooltip({ active, payload, formatValue, keyShape = "line", title }: ChartTooltipProps) {
  if (!active || !payload || payload.length === 0) return null
  const datum = (payload[0]?.payload ?? {}) as Record<string, unknown>
  const heading = title ? title(datum) : String(datum.xLabel ?? datum.label ?? "")

  return (
    <div className="min-w-40 rounded-md border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-md">
      {heading && <p className="mb-1 font-medium text-muted-foreground">{heading}</p>}
      <ul className="space-y-0.5">
        {payload.map((entry) => {
          const key = String(entry.dataKey ?? entry.name ?? "")
          const value = typeof entry.value === "number" ? entry.value : null
          return (
            <li key={key} className="flex items-center gap-2">
              <span
                aria-hidden
                className={keyShape === "line" ? "h-0.5 w-3 shrink-0 rounded-full" : "size-2.5 shrink-0 rounded-[2px]"}
                style={{ backgroundColor: entry.color }}
              />
              <span className="font-semibold tabular-nums text-foreground">
                {value == null ? "niet gemeten" : formatValue(value, key)}
              </span>
              <span className="truncate text-muted-foreground">{entry.name}</span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
