"use client"

import { GitCompareArrows, TrendingUp, Users, type LucideIcon } from "lucide-react"
import { useEffect, useState } from "react"

import { CustomerBenchmark } from "@/components/analytics/compare/CustomerBenchmark"
import { ScanCompare } from "@/components/analytics/compare/ScanCompare"
import { TrendCompare } from "@/components/analytics/compare/TrendCompare"
import { useRequest } from "@/components/analytics/compare/use-request"
import { ErrorNote } from "@/components/analytics/states"
import { fetchAnalyticsCustomers, fetchTrend, type TrendResponse } from "@/lib/analytics/api"
import { compareToUrlParams, type CompareMode, type CompareState } from "@/lib/analytics/compare"
import type { LaunchCustomer } from "@/lib/launch-checklist"
import { writeUrlParams } from "@/lib/url-state"
import { cn } from "@/lib/utils"

const MODES: { key: CompareMode; label: string; description: string; icon: LucideIcon }[] = [
  { key: "trend", label: "Trend", description: "Tot vier cijfers van één klant over de metingen heen.", icon: TrendingUp },
  { key: "scans", label: "Scan A/B", description: "Twee scans van één klant naast elkaar, alle cijfers.", icon: GitCompareArrows },
  { key: "klanten", label: "Klanten", description: "Alle klanten op één cijfer, van beste naar slechtste.", icon: Users },
]

/** Trend-data per klant, gedeeld door de modi Trend en Scan A/B. */
export type TrendRequest = { data: TrendResponse | null; error: string | null; loading: boolean }

/**
 * Pagina Vergelijken: modus-schakelaar met drie weergaven. Alle keuzes staan in
 * de URL (`?modus=&klant=&a=&b=&metric=`), zodat een refresh of gedeelde link
 * dezelfde weergave geeft.
 */
export function CompareView({ initialState }: { initialState: CompareState }) {
  const [state, setState] = useState<CompareState>(initialState)
  const [customers, setCustomers] = useState<LaunchCustomer[] | null>(null)
  const [customersError, setCustomersError] = useState<string | null>(null)

  useEffect(() => {
    fetchAnalyticsCustomers()
      .then(setCustomers)
      .catch((err: Error) => {
        setCustomers([])
        setCustomersError(`Klanten laden mislukt: ${err.message}`)
      })
  }, [])

  const needsTrend = state.mode !== "klanten" && !!state.customerId
  const trendRequest = useRequest<TrendResponse>(needsTrend ? state.customerId : null, (signal) =>
    fetchTrend(state.customerId ?? "", {}, { signal })
  )
  // Data van een vorige klant nooit tonen; herladen voor dezelfde klant mag (gedimd).
  const trend: TrendRequest = {
    ...trendRequest,
    data: trendRequest.data && trendRequest.data.customer.id === state.customerId ? trendRequest.data : null,
  }

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
          className="grid w-full grid-cols-3 gap-1 rounded-lg border bg-card p-1 sm:inline-grid sm:w-auto"
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

      {customersError && state.mode !== "klanten" && <ErrorNote>{customersError}</ErrorNote>}

      {state.mode === "trend" && (
        <TrendCompare
          customers={customers}
          customerId={state.customerId}
          onCustomerChange={(customerId) => update({ customerId, a: null, b: null })}
          trend={trend}
          selected={state.trendMetrics}
          onSelectedChange={(trendMetrics) => update({ trendMetrics })}
        />
      )}
      {state.mode === "scans" && (
        <ScanCompare
          customers={customers}
          customerId={state.customerId}
          onCustomerChange={(customerId) => update({ customerId, a: null, b: null })}
          trend={trend}
          a={state.a}
          b={state.b}
          onPairChange={(a, b) => update({ a, b })}
        />
      )}
      {state.mode === "klanten" && (
        <CustomerBenchmark
          metricKey={state.benchmarkMetric}
          onMetricChange={(benchmarkMetric) => update({ benchmarkMetric })}
          onOpenTrend={(customerId) => {
            update({ mode: "trend", customerId, a: null, b: null })
            window.scrollTo({ top: 0 })
          }}
        />
      )}
    </div>
  )
}
