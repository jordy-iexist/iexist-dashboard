"use client"

import { GitCompareArrows, TrendingUp, type LucideIcon } from "lucide-react"
import { useState } from "react"

import { ScanCompare } from "@/components/analytics/compare/ScanCompare"
import { TrendCompare } from "@/components/analytics/compare/TrendCompare"
import { useRequest, type RequestState } from "@/components/analytics/compare/use-request"
import { fetchTrend, type TrendResponse } from "@/lib/analytics/api"
import { compareToUrlParams, type CompareMode, type CompareState } from "@/lib/analytics/compare"
import { writeUrlParams } from "@/lib/url-state"
import { cn } from "@/lib/utils"

const MODES: { key: CompareMode; label: string; description: string; icon: LucideIcon }[] = [
  { key: "trend", label: "Trend", description: "Tot vier cijfers van deze klant over de metingen heen.", icon: TrendingUp },
  { key: "scans", label: "Scan A/B", description: "Twee scans van deze klant naast elkaar, alle cijfers.", icon: GitCompareArrows },
]

/** Trend-data van de klant, gedeeld door de modi Trend en Scan A/B. */
export type TrendRequest = RequestState<TrendResponse>

/**
 * Pagina Vergelijken: modus-schakelaar met twee weergaven voor de klant uit het
 * adres. Alle keuzes staan in de URL (`?klant=&modus=&a=&b=&metric=`), zodat een
 * refresh of gedeelde link dezelfde weergave geeft. Een andere klant (via de
 * sidebar) is een nieuwe navigatie en dus een nieuwe beginstand.
 */
export function CompareView({ customerId, initialState }: { customerId: string; initialState: CompareState }) {
  const [state, setState] = useState<CompareState>(initialState)
  const trend = useRequest<TrendResponse>(customerId, (signal) => fetchTrend(customerId, {}, { signal }))

  function update(patch: Partial<CompareState>) {
    setState((current) => {
      const next = { ...current, ...patch }
      writeUrlParams(compareToUrlParams(next))
      return next
    })
  }

  const active = MODES.find((m) => m.key === state.mode) ?? MODES[0]

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <div
          role="group"
          aria-label="Soort vergelijking"
          className="grid w-full grid-cols-2 gap-1 rounded-lg border bg-card p-1 sm:inline-grid sm:w-auto"
        >
          {MODES.map((mode) => {
            const selected = mode.key === state.mode
            return (
              <button
                key={mode.key}
                type="button"
                aria-pressed={selected}
                title={mode.description}
                onClick={() => update({ mode: mode.key })}
                className={cn(
                  "inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-md px-3 py-1.5 text-sm transition-colors",
                  selected
                    ? "bg-muted font-medium text-foreground shadow-xs"
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                <mode.icon className="size-4 shrink-0" aria-hidden />
                {mode.label}
              </button>
            )
          })}
        </div>
        <p className="text-sm text-muted-foreground">{active.description}</p>
      </div>

      {state.mode === "trend" && (
        <TrendCompare
          trend={trend}
          selected={state.trendMetrics}
          onSelectedChange={(trendMetrics) => update({ trendMetrics })}
        />
      )}
      {state.mode === "scans" && (
        <ScanCompare trend={trend} a={state.a} b={state.b} onPairChange={(a, b) => update({ a, b })} />
      )}
    </div>
  )
}
