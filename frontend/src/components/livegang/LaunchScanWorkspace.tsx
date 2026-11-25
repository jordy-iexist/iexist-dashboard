"use client"

import { RefreshCw } from "lucide-react"
import { useRouter } from "next/navigation"
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react"

import { Button } from "@/components/ui/button"
import { ChangesNavProvider } from "@/components/livegang/ChangesWorkspace"
import { MondayBoardSetting } from "@/components/livegang/MondayBoardSetting"
import { PanelRow } from "@/components/livegang/shared"
import { apiFetch, type LaunchScan } from "@/lib/launch-checklist"
import { seoGeoSlugForPhase, type SeoGeoPhase, type SeoGeoSlug } from "@/lib/seo-geo-sections"
import { changesHref } from "@/lib/site-changes"

async function fetchPhaseState(customerId: string) {
  const query = `customer_website_id=${encodeURIComponent(customerId)}&limit=20`
  const [p1, p2, p3, p4] = await Promise.all([
    apiFetch<{ items: LaunchScan[] }>(`/scans?${query}&phase=1`),
    apiFetch<{ items: LaunchScan[] }>(`/scans?${query}&phase=2`),
    apiFetch<{ items: LaunchScan[] }>(`/scans?${query}&phase=3`),
    apiFetch<{ items: LaunchScan[] }>(`/scans?${query}&phase=4`),
  ])
  const phase1 = p1.items.filter((s) => (s.phase ?? 1) === 1)
  const phase2 = p2.items.filter((s) => s.phase === 2)
  const phase3 = p3.items.filter((s) => s.phase === 3)
  const phase4 = p4.items.filter((s) => s.phase === 4)
  // Lijsten zijn gesorteerd op created_at desc: find() geeft de nieuwste.
  const latest1 = phase1.find((s) => s.status === "completed")
  const latest2 = phase2.find((s) => s.status === "completed")
  // Tijdens een AI-analyse staat de (al voltooide) scan tijdelijk op 'analyzing'.
  const latest3 = phase3.find((s) => s.status === "completed" || s.status === "analyzing")
  // Verouderd: de fase is gebaseerd op een oudere nulmeting dan de nieuwste (ook lopende)
  // nulmeting. Mislukte of geannuleerde nulmetingen tellen niet mee.
  const newest1 = phase1.find((s) => s.status !== "failed" && s.status !== "canceled")
  const isOutdated = (scan: LaunchScan | undefined) =>
    !!scan && !!newest1 && scan.source_scan_id !== newest1.id
  return {
    done: {
      1: !!latest1,
      2: !!latest2,
      3: !!latest3,
      // Fase 4 is terugkerend: afgerond zodra er een voltooide kwartaalscan is.
      4: phase4.some((s) => s.status === "completed"),
    } as Record<number, boolean>,
    outdated: {
      2: isOutdated(latest2),
      3: isOutdated(latest3),
    } as Record<number, boolean>,
    hasGeoScans: phase2.length > 0,
    hasContentScans: phase3.length > 0,
    hasQuarterlyScans: phase4.length > 0,
  }
}

type PhaseState = Awaited<ReturnType<typeof fetchPhaseState>>

/** Waarom fase 2 t/m 4 nog dicht zit: de melding op de pagina van die fase. */
const LOCK_REASONS: Record<Exclude<SeoGeoPhase, 1>, string> = {
  2: "Voer eerst een voltooide nulmeting (fase 1) uit.",
  3: "Voer eerst een voltooide GEO/SEO-scan (fase 2) uit.",
  4: "Voer eerst een voltooide content-scan (fase 3) uit.",
}

/** Vergrendeltekst als de vorige fase nog niet is afgerond, anders undefined. */
export function phaseLockReason(phase: SeoGeoPhase, done: Record<number, boolean>): string | undefined {
  return phase === 1 || done[phase - 1] ? undefined : LOCK_REASONS[phase]
}

/** Verste fase die al gestart is: daar opent de scan zonder gekozen onderdeel. */
function furthestStartedPhase(state: PhaseState): SeoGeoPhase {
  return state.done[3] && state.hasQuarterlyScans
    ? 4
    : state.done[2] && state.hasContentScans
      ? 3
      : state.done[1] && state.hasGeoScans
        ? 2
        : 1
}

type ScanPhases = {
  customerId: string
  done: Record<number, boolean>
  /** Afgeronde fases (2 en 3) die op een oudere nulmeting dan de nieuwste zijn gebaseerd. */
  outdated: Record<number, boolean>
  /** Subpagina van de verste gestarte fase. */
  furthest: SeoGeoSlug
  /** Fasestatus opnieuw ophalen (na een scan, of als een fase iets wijzigt). */
  refreshPhases: () => void
}

const ScanPhasesContext = createContext<ScanPhases | null>(null)

/** Fasestatus van de klant voor de subpagina's van de scan (alleen binnen `LaunchScanWorkspace`). */
export function useScanPhases(): ScanPhases {
  const value = useContext(ScanPhasesContext)
  if (!value) throw new Error("useScanPhases werkt alleen binnen LaunchScanWorkspace")
  return value
}

/**
 * Schil om de subpagina's van de SEO/GEO-scan van een klant (layout): de kop en de fasestatus.
 * Wisselen tussen de onderdelen gaat via het menu (SEO/GEO-scan in de zijbalk).
 * De subpagina verschijnt pas als de fasestatus de eerste keer is geladen.
 */
export function LaunchScanWorkspace({
  customerId,
  header,
  children,
}: {
  customerId: string
  header: React.ReactNode
  children: React.ReactNode
}) {
  const router = useRouter()
  const [phaseState, setPhaseState] = useState<PhaseState | null>(null)
  // Eerste keer laden mislukt: geen fase tonen (die zou ten onrechte "vergrendeld" lijken).
  const [loadError, setLoadError] = useState<string | null>(null)
  // Verversen na de eerste keer laden mislukt: de vorige fasestatus blijft staan.
  const [refreshError, setRefreshError] = useState(false)
  // Ophogen = de fasestatus opnieuw laden (knop "Opnieuw proberen").
  const [loadAttempt, setLoadAttempt] = useState(0)

  useEffect(() => {
    let cancelled = false
    fetchPhaseState(customerId)
      .then((state) => {
        if (cancelled) return
        setPhaseState(state)
        setLoadError(null)
        setRefreshError(false)
      })
      .catch((err: Error) => {
        if (!cancelled) setLoadError(err.message || "Onbekende fout")
      })
    return () => {
      cancelled = true
    }
  }, [customerId, loadAttempt])

  const refreshPhases = useCallback(() => {
    fetchPhaseState(customerId)
      .then((state) => {
        setPhaseState(state)
        setRefreshError(false)
      })
      .catch(() => setRefreshError(true))
  }, [customerId])

  // "Bekijk in Aanpassingen"-links: naar Aanpassingen, eventueel direct op één pagina.
  const openChanges = useCallback(
    (url: string | null) => router.push(changesHref(customerId, url)),
    [router, customerId]
  )

  const done = useMemo(() => phaseState?.done ?? {}, [phaseState])
  const outdated = useMemo(() => phaseState?.outdated ?? {}, [phaseState])
  const furthest = phaseState ? seoGeoSlugForPhase(furthestStartedPhase(phaseState)) : null

  const context = useMemo<ScanPhases | null>(
    () => (furthest ? { customerId, done, outdated, furthest, refreshPhases } : null),
    [customerId, done, outdated, furthest, refreshPhases]
  )

  function retryLoad() {
    setLoadError(null)
    setLoadAttempt((n) => n + 1)
  }

  if (phaseState === null && loadError) {
    return (
      <div className="space-y-6">
        <header className="space-y-2">{header}</header>
        <PanelRow tone="error" className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <span className="min-w-0 flex-1">
            De fases van deze klant konden niet worden geladen, dus we weten niet welke fase klaar is. ({loadError})
          </span>
          <Button size="sm" variant="outline" onClick={retryLoad}>
            <RefreshCw /> Opnieuw proberen
          </Button>
        </PanelRow>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0 space-y-2">{header}</div>
        <div className="space-y-2 lg:shrink-0">
          {refreshError && (
            <p className="text-xs text-amber-800 lg:text-right dark:text-amber-300">
              De fasestatus kon niet worden ververst; of een fase open of verouderd is, kan achterlopen.
            </p>
          )}
          <MondayBoardSetting customerId={customerId} align="end" />
        </div>
      </header>
      {context && (
        <ScanPhasesContext.Provider value={context}>
          <ChangesNavProvider customerId={customerId} onOpen={openChanges}>
            {children}
          </ChangesNavProvider>
        </ScanPhasesContext.Provider>
      )}
    </div>
  )
}
