"use client"

import { Download, Loader2, Play, Square, Trash2 } from "lucide-react"
import { useSearchParams } from "next/navigation"
import { useCallback, useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { AiChecksTab } from "@/components/livegang/AiChecksTab"
import { AiVisibilityTab } from "@/components/livegang/AiVisibilityTab"
import { InventoryTab } from "@/components/livegang/InventoryTab"
import { IssuesTab } from "@/components/livegang/IssuesTab"
import { OverviewTab } from "@/components/livegang/OverviewTab"
import {
  isActive,
  PanelRow,
  PanelTabs,
  PhasePanel,
  PollingFailedNotice,
  ScanProgress,
  ScanStatusBadge,
} from "@/components/livegang/shared"
import { VitalsTab } from "@/components/livegang/VitalsTab"
import {
  API_BASE,
  apiFetch,
  formatDateTime,
  STATUS_LABELS,
  type LaunchScan,
  type LaunchScanDetail,
} from "@/lib/launch-checklist"
import { usePolling } from "@/hooks/use-polling"
import { pickUrlChoice, writeUrlParams } from "@/lib/url-state"

const TABS = [
  { key: "overview", label: "Overzicht" },
  { key: "issues", label: "Actiepunten" },
  { key: "inventory", label: "Inventaris" },
  { key: "vitals", label: "Core Web Vitals" },
  { key: "ai", label: "AI-vindbaarheid" },
  { key: "visibility", label: "AI-zichtbaarheid" },
] as const

type TabKey = (typeof TABS)[number]["key"]
const TAB_KEYS = TABS.map((t) => t.key)

/** Fase 1 · Nulmeting & AI scan. */
export function NulmetingWorkspace({ customerId, onChange }: { customerId: string; onChange: () => void }) {
  const [scans, setScans] = useState<LaunchScan[] | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [scan, setScan] = useState<LaunchScanDetail | null>(null)
  // Tabblad uit het adres van de router: bij navigeren binnen de app staat window.location
  // tijdens de eerste render nog op het vorige adres.
  const searchParams = useSearchParams()
  const [tab, setTabState] = useState<TabKey>(() => pickUrlChoice(searchParams.get("tab"), TAB_KEYS, "overview"))
  const setTab = (next: TabKey) => {
    setTabState(next)
    writeUrlParams({ tab: next })
  }
  const [maxPages, setMaxPages] = useState(500)
  const [vitalsMax, setVitalsMax] = useState(100)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadScans = useCallback(async () => {
    const result = await apiFetch<{ items: LaunchScan[] }>(
      `/scans?customer_website_id=${encodeURIComponent(customerId)}&phase=1&limit=20`
    )
    // Client-side ook filteren: een oudere backend negeert ?phase=.
    const items = result.items.filter((s) => (s.phase ?? 1) === 1)
    setScans(items)
    onChange()
    return items
  }, [customerId, onChange])

  useEffect(() => {
    loadScans()
      .then((items) => setSelectedId((current) => current ?? items[0]?.id ?? null))
      .catch((err: Error) => setError(err.message))
  }, [loadScans])

  const loadScan = useCallback(async (id: string) => {
    const detail = await apiFetch<LaunchScanDetail>(`/scans/${id}`)
    setScan(detail)
    return detail
  }, [])

  // Detail laden bij het wisselen van scan.
  useEffect(() => {
    if (!selectedId) {
      setScan(null)
      return
    }
    loadScan(selectedId).catch((err: Error) => setError(err.message))
  }, [selectedId, loadScan])

  // Pollen zolang de geselecteerde scan loopt; daarna de scanlijst verversen.
  const { failing: pollingFailed } = usePolling(
    async () => {
      if (!selectedId) return
      const next = await loadScan(selectedId)
      if (!isActive(next.status)) await loadScans()
    },
    scan !== null && scan.id === selectedId && isActive(scan.status),
    3000
  )

  async function startScan() {
    setBusy(true)
    setError(null)
    try {
      const created = await apiFetch<LaunchScanDetail>("/scans", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ customer_website_id: customerId, max_pages: maxPages, vitals_max_pages: vitalsMax }),
      })
      await loadScans()
      setTab("overview")
      setSelectedId(created.id)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function cancelScan() {
    if (!scan) return
    setBusy(true)
    try {
      await apiFetch(`/scans/${scan.id}/cancel`, { method: "POST" })
      await loadScan(scan.id)
      await loadScans()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function deleteScan() {
    if (!scan || !window.confirm("Deze scan en alle resultaten verwijderen?")) return
    setBusy(true)
    try {
      await apiFetch(`/scans/${scan.id}`, { method: "DELETE" })
      const items = await loadScans()
      setSelectedId(items[0]?.id ?? null)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const running = scan ? isActive(scan.status) : false
  const anyRunning = scans?.some((s) => isActive(s.status)) ?? false
  const hasResults = scan !== null && (scan.status === "completed" || scan.status === "analyzing" || scan.status === "vitals")

  return (
    <div className="space-y-4">
      <PhasePanel
        title="Fase 1 · Nulmeting & AI scan"
        description={
          <>
            Haalt de sitemap op, maakt een site-inventaris (statuscodes, indexeerbaarheid, title/meta/H1, links,
            afbeeldingen, structured data), meet de Core Web Vitals per pagina (mobiel), controleert de
            AI-vindbaarheid en laat de Nulmeting-agent een rapport met actiepunten schrijven.
          </>
        }
      >
        {scans && scans.length === 0 && (
          <PanelRow>
            <span className="text-muted-foreground">Nog geen scans voor deze klant: start hieronder de eerste scan.</span>
          </PanelRow>
        )}

        {scan && (
          <PanelRow className="space-y-3">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
              <ScanStatusBadge status={scan.status} />
              <span className="text-muted-foreground">
                Gestart {formatDateTime(scan.created_at)}
                {scan.completed_at && ` · klaar ${formatDateTime(scan.completed_at)}`}
              </span>
              <div className="ml-auto flex flex-wrap items-center gap-2">
                {scans && scans.length > 1 && (
                  <select
                    value={selectedId ?? ""}
                    onChange={(e) => setSelectedId(e.target.value)}
                    aria-label="Scangeschiedenis"
                    title="Scangeschiedenis"
                    className="h-8 rounded-md border bg-background px-2 text-sm"
                  >
                    {scans.map((s) => (
                      <option key={s.id} value={s.id}>
                        {formatDateTime(s.created_at)} · {STATUS_LABELS[s.status]}
                      </option>
                    ))}
                  </select>
                )}
                {running ? (
                  <Button size="sm" variant="ghost" onClick={cancelScan} disabled={busy}>
                    <Square /> Annuleren
                  </Button>
                ) : (
                  <>
                    {scan.status === "completed" && (
                      <>
                        <Button size="sm" variant="outline" asChild>
                          <a href={`${API_BASE}/scans/${scan.id}/export?kind=inventory`}>
                            <Download /> Inventaris (CSV)
                          </a>
                        </Button>
                        <Button size="sm" variant="outline" asChild>
                          <a href={`${API_BASE}/scans/${scan.id}/export?kind=issues`}>
                            <Download /> Actiepunten (CSV)
                          </a>
                        </Button>
                      </>
                    )}
                    <Button size="sm" variant="ghost" onClick={deleteScan} disabled={busy} title="Scan verwijderen">
                      <Trash2 /> Verwijderen
                    </Button>
                  </>
                )}
              </div>
            </div>
            {running && <ScanProgress scan={scan} bare />}
            <PollingFailedNotice failing={pollingFailed} />
            {scan.status === "failed" && (
              <p className="text-red-700 dark:text-red-400">Scan mislukt: {scan.error_message ?? "onbekende fout"}</p>
            )}
          </PanelRow>
        )}

        <PanelRow tone="muted">
          <div className="flex flex-wrap items-end gap-3">
            <label className="space-y-1">
              <span className="block text-xs text-muted-foreground">Max. pagina&apos;s</span>
              <Input type="number" min={1} max={2000} value={maxPages} onChange={(e) => setMaxPages(Number(e.target.value) || 1)} className="w-28 bg-background" />
            </label>
            <label className="space-y-1">
              <span className="block text-xs text-muted-foreground">Max. CWV-metingen</span>
              <Input type="number" min={0} max={500} value={vitalsMax} onChange={(e) => setVitalsMax(Math.max(0, Number(e.target.value) || 0))} className="w-28 bg-background" />
            </label>
            <Button onClick={startScan} disabled={busy || anyRunning}>
              {busy ? <Loader2 className="animate-spin" /> : <Play />}
              {anyRunning ? "Scan loopt…" : "Start nieuwe scan"}
            </Button>
          </div>
        </PanelRow>

        {error && <PanelRow tone="error">{error}</PanelRow>}
      </PhasePanel>

      {hasResults && (
        <PanelTabs
          tabs={TABS.map((t) => ({
            key: t.key,
            label:
              t.key === "issues" && scan.summary_stats?.issues ? `${t.label} (${scan.summary_stats.issues.total})` : t.label,
          }))}
          active={tab}
          onSelect={setTab}
        />
      )}

      {scan && hasResults && (
        <>
          {tab === "overview" && <OverviewTab scan={scan} />}
          {tab === "issues" && <IssuesTab scanId={scan.id} customerId={customerId} />}
          {tab === "inventory" && <InventoryTab scanId={scan.id} hasAhrefs={Boolean(scan.ahrefs)} />}
          {tab === "vitals" && <VitalsTab scanId={scan.id} measuring={scan.status === "vitals"} />}
          {tab === "ai" && <AiChecksTab checks={scan.ai_checks} />}
          {tab === "visibility" && <AiVisibilityTab scanId={scan.id} snapshot={scan.proranktracker} />}
        </>
      )}
    </div>
  )
}
