"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { RefreshCw } from "lucide-react"

import { ErrorNote } from "@/components/analytics/states"
import { BureauSkeleton } from "@/components/bureau/BureauSkeleton"
import { CustomersTable } from "@/components/bureau/CustomersTable"
import { SignalsCard } from "@/components/bureau/SignalsCard"
import { KpiCard } from "@/components/klanten/dashboard/KpiCard"
import { Button } from "@/components/ui/button"
import { fetchOverview, refreshRankings, type AgencyOverview } from "@/lib/agency-overview"
import { WORK_BOARD_URL } from "@/lib/work-queue"
import { cn } from "@/lib/utils"

const TIME_ZONE = "Europe/Amsterdam"
const dayFormat = new Intl.DateTimeFormat("nl-NL", { timeZone: TIME_ZONE, year: "numeric", month: "2-digit", day: "2-digit" })
const dayMonthFormat = new Intl.DateTimeFormat("nl-NL", { timeZone: TIME_ZONE, day: "numeric", month: "short" })
const timeFormat = new Intl.DateTimeFormat("nl-NL", { timeZone: TIME_ZONE, hour: "2-digit", minute: "2-digit" })

/** "vandaag 07:00", "24 nov 07:00" of "nog niet opgehaald" (Amsterdamse tijd). */
export function formatFetchedAt(value: string | null, now = new Date()): string {
  if (!value) return "nog niet opgehaald"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return "nog niet opgehaald"
  const time = timeFormat.format(date)
  if (dayFormat.format(date) === dayFormat.format(now)) return `vandaag ${time}`
  return `${dayMonthFormat.format(date).replace(/\.$/, "")} ${time}`
}

function plural(count: number, one: string, many: string) {
  return `${count.toLocaleString("nl-NL")} ${count === 1 ? one : many}`
}

function errorMessage(error: unknown) {
  return error instanceof Error && error.message ? error.message : "Er ging iets mis."
}

function isAbort(error: unknown) {
  return error instanceof DOMException && error.name === "AbortError"
}

type LoadState =
  | { status: "loading" }
  | { status: "error"; error: string }
  | { status: "ready"; data: AgencyOverview }

/** Bureaubreed overzicht: kop, twee tegels, signalen en de klantentabel. */
export function BureauOverviewPage() {
  const [state, setState] = useState<LoadState>({ status: "loading" })
  const [refreshing, setRefreshing] = useState(false)
  const [refreshError, setRefreshError] = useState<string | null>(null)
  const controllerRef = useRef<AbortController | null>(null)

  /** Haalt het overzicht op; een nieuw verzoek breekt een lopend verzoek af. */
  const load = useCallback(async () => {
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller
    try {
      const data = await fetchOverview(controller.signal)
      setState({ status: "ready", data })
    } catch (error) {
      if (isAbort(error)) return
      setState({ status: "error", error: errorMessage(error) })
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  // Afbreken bij weggaan.
  useEffect(() => () => controllerRef.current?.abort(), [])

  const retry = () => {
    setState({ status: "loading" })
    void load()
  }

  const refresh = async () => {
    if (refreshing) return
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller
    setRefreshing(true)
    setRefreshError(null)
    try {
      const data = await refreshRankings(controller.signal)
      setState({ status: "ready", data })
    } catch (error) {
      if (isAbort(error)) return
      setRefreshError(`Vernieuwen is mislukt: ${errorMessage(error)}`)
    } finally {
      if (controllerRef.current === controller) setRefreshing(false)
    }
  }

  if (state.status === "loading") return <BureauSkeleton />

  const data = state.status === "ready" ? state.data : null
  const kpis = data?.kpis

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 space-y-1">
          <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">Bureau</p>
          <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Bureau-overzicht</h1>
          {data && (
            <p className="text-sm text-muted-foreground">
              {plural(data.kpis.customers, "klant", "klanten")} · week {data.week} · posities bijgewerkt{" "}
              {formatFetchedAt(data.rankings_fetched_at)}
            </p>
          )}
        </div>

        {data && (
          <div className="flex flex-col items-end gap-1">
            <Button
              type="button"
              size="sm"
              variant="secondary"
              onClick={() => void refresh()}
              disabled={refreshing}
              aria-busy={refreshing}
              title="Haalt de posities van alle klanten direct opnieuw op uit ProRankTracker"
            >
              <RefreshCw className={cn(refreshing && "animate-spin")} aria-hidden="true" />
              {refreshing ? "Bezig…" : "Posities vernieuwen"}
            </Button>
            {refreshError && (
              <p role="alert" className="max-w-xs text-right text-xs text-destructive">
                {refreshError}
              </p>
            )}
          </div>
        )}
      </header>

      {state.status === "error" ? (
        <ErrorNote>
          <span className="flex flex-wrap items-center gap-3">
            <span>Het overzicht kon niet geladen worden: {state.error}</span>
            <Button type="button" variant="outline" size="sm" onClick={retry}>
              Opnieuw proberen
            </Button>
          </span>
        </ErrorNote>
      ) : (
        data &&
        kpis && (
          <>
            <div className="grid gap-4 sm:grid-cols-2">
              <KpiCard
                label="Klanten"
                value={kpis.customers.toLocaleString("nl-NL")}
                hint={
                  kpis.customers_attention > 0
                    ? `${kpis.customers_attention.toLocaleString("nl-NL")} ${kpis.customers_attention === 1 ? "vraagt" : "vragen"} aandacht`
                    : "alles op koers"
                }
                tone={kpis.customers_attention > 0 ? "warn" : "good"}
              />
              <KpiCard
                label="Open taken"
                value={kpis.open_tasks.toLocaleString("nl-NL")}
                hint={
                  kpis.open_tasks_high > 0
                    ? `${kpis.open_tasks_high.toLocaleString("nl-NL")} met hoge prioriteit`
                    : "geen met hoge prioriteit"
                }
                tone={kpis.open_tasks_high > 0 ? "accent" : "muted"}
                href={WORK_BOARD_URL}
              />
            </div>

            <SignalsCard signals={data.signals} />
            <CustomersTable customers={data.customers} />
          </>
        )
      )}
    </div>
  )
}
