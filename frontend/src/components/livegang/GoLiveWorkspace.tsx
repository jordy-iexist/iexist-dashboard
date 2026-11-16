"use client"

import { Download, Loader2, Play, Printer, Square, Trash2 } from "lucide-react"
import Link from "next/link"
import { useCallback, useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { ChecklistTab } from "@/components/livegang/ChecklistTab"
import { goLiveItemDetails } from "@/components/livegang/GoLiveDetails"
import { InventoryTab } from "@/components/livegang/InventoryTab"
import { MondayBoardSetting } from "@/components/livegang/MondayBoardSetting"
import {
  GOLIVE_STEPS,
  isActive,
  PanelRow,
  PanelTabs,
  PercentRing,
  PhasePanel,
  PollingFailedNotice,
  ScanProgress,
  ScanStatusBadge,
} from "@/components/livegang/shared"
import { usePolling } from "@/hooks/use-polling"
import {
  API_BASE,
  apiFetch,
  formatDateTime,
  syncMondayLinks,
  type GoLiveChecklist,
  type LaunchScan,
  type LaunchScanDetail,
} from "@/lib/launch-checklist"
import { readUrlChoice, writeUrlParams } from "@/lib/url-state"

const TABS = [
  { key: "checklist", label: "Checklist" },
  { key: "pages", label: "Pagina's" },
] as const

type TabKey = (typeof TABS)[number]["key"]
const TAB_KEYS = TABS.map((t) => t.key)

/**
 * Livegangchecklist van één klant: controle direct na het live zetten van een
 * nieuwe website. Werkt zonder SEO/GEO-scan. De checklist blijft altijd
 * afvinkbaar, ook vóór de eerste scan en tijdens een scan; tijdens een nieuwe
 * scan staan de automatische resultaten van de vorige (voltooide) scan erbij.
 */
export function GoLiveWorkspace({ customerId }: { customerId: string }) {
  const [checklist, setChecklist] = useState<GoLiveChecklist | null>(null)
  const [latest, setLatest] = useState<LaunchScanDetail | null>(null)
  const [storedTab, setTabState] = useState<TabKey>(() => readUrlChoice("tab", TAB_KEYS, "checklist"))
  const setTab = (next: TabKey) => {
    setTabState(next)
    writeUrlParams({ tab: next })
  }
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchChecklist = useCallback(
    () => apiFetch<GoLiveChecklist>(`/customers/${customerId}/golive-checklist`),
    [customerId]
  )

  // Laatste livegangscan, ook als die loopt of mislukt is (de checklist toont de laatste voltooide).
  const fetchLatest = useCallback(async () => {
    const result = await apiFetch<{ items: LaunchScan[] }>(
      `/scans?customer_website_id=${encodeURIComponent(customerId)}&phase=5&limit=1`
    )
    const first = result.items.find((s) => s.phase === 5)
    return first ? apiFetch<LaunchScanDetail>(`/scans/${first.id}`) : null
  }, [customerId])

  // Na een wijziging (afvinken, notitie, scan klaar) opnieuw ophalen.
  const loadChecklist = useCallback(async () => {
    const data = await fetchChecklist()
    setChecklist(data)
    return data
  }, [fetchChecklist])

  const loadLatest = useCallback(async () => {
    const detail = await fetchLatest()
    setLatest(detail)
    return detail
  }, [fetchLatest])

  useEffect(() => {
    let cancelled = false
    Promise.all([fetchChecklist(), fetchLatest()])
      .then(([data, detail]) => {
        if (cancelled) return
        setChecklist(data)
        setLatest(detail)
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message)
      })
    return () => {
      cancelled = true
    }
  }, [fetchChecklist, fetchLatest])

  // In Monday verwijderde items: koppeling opruimen en de checklist verversen.
  useEffect(() => {
    let cancelled = false
    void syncMondayLinks(customerId).then((cleared) => {
      if (!cancelled && cleared > 0) void loadChecklist().catch(() => {})
    })
    return () => {
      cancelled = true
    }
  }, [customerId, loadChecklist])

  const running = latest ? isActive(latest.status) : false

  // Pollen zolang de scan loopt; daarna de checklist met de nieuwe resultaten ophalen.
  const { failing: pollingFailed } = usePolling(
    async () => {
      const next = await loadLatest()
      if (!next || !isActive(next.status)) await loadChecklist()
    },
    running,
    3000
  )

  async function startScan() {
    setBusy(true)
    setError(null)
    try {
      await apiFetch<LaunchScanDetail>(`/customers/${customerId}/golive-scans`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      })
      await loadLatest()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function cancelScan() {
    if (!latest) return
    setBusy(true)
    try {
      await apiFetch(`/scans/${latest.id}/cancel`, { method: "POST" })
      await loadLatest()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function deleteScan() {
    if (!latest || !window.confirm("Deze livegangscan verwijderen? Handmatige afvinkstatussen blijven bewaard.")) return
    setBusy(true)
    try {
      await apiFetch(`/scans/${latest.id}`, { method: "DELETE" })
      await Promise.all([loadLatest(), loadChecklist()])
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const completedScan = checklist?.scan ?? null
  // De pagina's horen bij de laatste voltooide scan; zonder die scan alleen de checklist.
  const tab: TabKey = completedScan ? storedTab : "checklist"
  const warnings = completedScan?.warnings ?? []

  return (
    <div className="space-y-4">
      {/* Zelfde bord als de SEO/GEO-scan; de livegangchecklist heeft er een eigen groep op. */}
      <section className="overflow-hidden rounded-lg border bg-card [&>div]:border-t-0">
        <MondayBoardSetting customerId={customerId} />
      </section>

      <PhasePanel
        title="Livegangchecklist"
        description={
          <>
            Controle direct na het live zetten van de nieuwe website, op het live domein: HTTPS en redirects,
            restanten van de testomgeving, indexatie, tracking en cookies, en formulieren. De scan vult de
            automatische punten; je status en notities blijven per klant bewaard.
          </>
        }
        aside={
          checklist && (
            <div className="flex items-center gap-3">
              <PercentRing percent={checklist.percent} size={64} />
              <div className="text-sm">
                <p className="font-medium">
                  {checklist.done} / {checklist.total}
                </p>
                <p className="text-xs text-muted-foreground">punten afgerond</p>
              </div>
            </div>
          )
        }
      >
        <PanelRow className="space-y-3">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            {latest ? (
              <>
                <ScanStatusBadge status={latest.status} />
                <span className="text-muted-foreground">
                  {latest.status === "completed"
                    ? `Gescand ${formatDateTime(latest.completed_at ?? latest.created_at)}`
                    : `Gestart ${formatDateTime(latest.created_at)}`}
                </span>
              </>
            ) : (
              <span className="text-muted-foreground">Nog niet gescand.</span>
            )}
            <div className="ml-auto flex flex-wrap items-center gap-2">
              {latest && running && (
                <Button size="sm" variant="ghost" onClick={cancelScan} disabled={busy}>
                  <Square /> Annuleren
                </Button>
              )}
              {latest && (latest.status === "failed" || latest.status === "canceled") && (
                <Button size="sm" variant="ghost" onClick={deleteScan} disabled={busy}>
                  <Trash2 /> Verwijderen
                </Button>
              )}
              {/* Per klant, niet per scan: de checklist bestaat ook zonder scan (alleen handmatige status). */}
              {checklist && (
                <Button size="sm" variant="outline" asChild>
                  <a href={`${API_BASE}/customers/${customerId}/golive-checklist/export`}>
                    <Download /> Checklist (CSV)
                  </a>
                </Button>
              )}
              {checklist && (
                <Button size="sm" variant="outline" asChild>
                  <Link href={`/dashboard/livegang/oplevering/${customerId}/checklist/print`} target="_blank">
                    <Printer /> Printversie / PDF
                  </Link>
                </Button>
              )}
            </div>
          </div>
          {latest && running && <ScanProgress scan={latest} steps={GOLIVE_STEPS} bare />}
          <PollingFailedNotice failing={pollingFailed} />
          {latest?.status === "failed" && (
            <p className="text-red-700 dark:text-red-400">Scan mislukt: {latest.error_message ?? "onbekende fout"}</p>
          )}
        </PanelRow>

        <PanelRow tone="muted">
          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={startScan} disabled={busy || running}>
              {busy ? <Loader2 className="animate-spin" /> : <Play />}
              {running ? "Scan loopt…" : completedScan || latest ? "Opnieuw scannen" : "Start livegangscan"}
            </Button>
            <p className="text-xs text-muted-foreground">
              Crawlt de live site (tot 500 pagina&apos;s) en controleert de automatische punten. Duurt een paar
              minuten.
            </p>
          </div>
        </PanelRow>

        {warnings.length > 0 && (
          <PanelRow tone="warning">
            <ul className="space-y-1 text-xs">
              {warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          </PanelRow>
        )}

        {error && <PanelRow tone="error">{error}</PanelRow>}

        {checklist && (
          <PanelTabs
            tabs={TABS.map((t) => ({ key: t.key, label: t.label, disabled: t.key !== "checklist" && !completedScan }))}
            active={tab}
            onSelect={setTab}
          />
        )}
      </PhasePanel>

      {checklist && (
        <section className="space-y-4">
          {tab === "checklist" && (
            <>
              {running && (
                <p className="text-sm text-muted-foreground">
                  {completedScan
                    ? `Er loopt een nieuwe scan. Hieronder staan de automatische resultaten van de vorige scan (${formatDateTime(
                        completedScan.completed_at ?? completedScan.created_at
                      )}); ze worden bijgewerkt zodra de scan klaar is. Afvinken kan gewoon.`
                    : "De scan loopt: de automatische resultaten verschijnen hier zodra hij klaar is. Afvinken kan nu al."}
                </p>
              )}
              {!running && !completedScan && (
                <p className="text-sm text-muted-foreground">
                  Nog geen livegangscan. Start een scan om de automatische punten te laten controleren, of vink de
                  punten met de hand af. De uitleg per punt vertelt wat je controleert.
                </p>
              )}
              <ChecklistTab
                checklist={checklist}
                customerId={customerId}
                path="golive-checklist"
                itemDetails={goLiveItemDetails}
                onChanged={loadChecklist}
              />
            </>
          )}
          {tab === "pages" && completedScan && <InventoryTab scanId={completedScan.id} />}
        </section>
      )}
    </div>
  )
}
