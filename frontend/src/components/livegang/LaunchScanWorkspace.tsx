"use client"

import { Download, Loader2, Play, Square, Trash2 } from "lucide-react"
import { useCallback, useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { AiChecksTab } from "@/components/livegang/AiChecksTab"
import { ContentWorkspace } from "@/components/livegang/ContentWorkspace"
import { GeoWorkspace } from "@/components/livegang/GeoWorkspace"
import { InventoryTab } from "@/components/livegang/InventoryTab"
import { IssuesTab } from "@/components/livegang/IssuesTab"
import { MondayBoardSetting } from "@/components/livegang/MondayBoardSetting"
import { OverviewTab } from "@/components/livegang/OverviewTab"
import { isActive, PhaseStepper, ScanProgress, ScanStatusBadge } from "@/components/livegang/shared"
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
import { readUrlChoice, readUrlParam, writeUrlParams } from "@/lib/url-state"
import { cn } from "@/lib/utils"

const TABS = [
  { key: "overview", label: "Overzicht" },
  { key: "issues", label: "Actiepunten" },
  { key: "inventory", label: "Inventaris" },
  { key: "vitals", label: "Core Web Vitals" },
  { key: "ai", label: "AI-vindbaarheid" },
] as const

type TabKey = (typeof TABS)[number]["key"]
const TAB_KEYS = TABS.map((t) => t.key)

async function fetchPhaseState(customerId: string) {
  const query = `customer_website_id=${encodeURIComponent(customerId)}&limit=20`
  const [p1, p2, p3] = await Promise.all([
    apiFetch<{ items: LaunchScan[] }>(`/scans?${query}&phase=1`),
    apiFetch<{ items: LaunchScan[] }>(`/scans?${query}&phase=2`),
    apiFetch<{ items: LaunchScan[] }>(`/scans?${query}&phase=3`),
  ])
  const phase1 = p1.items.filter((s) => (s.phase ?? 1) === 1)
  const phase2 = p2.items.filter((s) => s.phase === 2)
  const phase3 = p3.items.filter((s) => s.phase === 3)
  return {
    done: {
      1: phase1.some((s) => s.status === "completed"),
      2: phase2.some((s) => s.status === "completed"),
      // Tijdens een AI-analyse staat de (al voltooide) scan tijdelijk op 'analyzing'.
      3: phase3.some((s) => s.status === "completed" || s.status === "analyzing"),
    } as Record<number, boolean>,
    hasGeoScans: phase2.length > 0,
    hasContentScans: phase3.length > 0,
  }
}

export function LaunchScanWorkspace({ customerId }: { customerId: string }) {
  const [phase, setPhase] = useState<number | null>(null)
  const [done, setDone] = useState<Record<number, boolean>>({})

  useEffect(() => {
    let cancelled = false
    fetchPhaseState(customerId)
      .then((state) => {
        if (cancelled) return
        setDone(state.done)
        // De fase uit de URL (?fase=) gaat voor, zodat een refresh op dezelfde fase
        // blijft. Zonder keuze: fase 2 openen als die al eerder gestart is.
        const fromUrl = readUrlParam("fase")
        const fallback = state.done[2] && state.hasContentScans ? 3 : state.done[1] && state.hasGeoScans ? 2 : 1
        const initial =
          fromUrl === "1"
            ? 1
            : fromUrl === "2" && state.done[1]
              ? 2
              : fromUrl === "3" && state.done[2]
                ? 3
                : fallback
        setPhase((current) => current ?? initial)
      })
      .catch(() => {
        if (!cancelled) setPhase((current) => current ?? (readUrlParam("fase") === "2" ? 2 : 1))
      })
    return () => {
      cancelled = true
    }
  }, [customerId])

  const refreshPhases = useCallback(() => {
    fetchPhaseState(customerId)
      .then((state) => setDone(state.done))
      .catch(() => {})
  }, [customerId])

  return (
    <div className="space-y-6">
      <PhaseStepper
        active={phase ?? 1}
        completed={done}
        locked={{
          2: done[1] ? undefined : "Voer eerst een voltooide nulmeting (fase 1) uit.",
          3: done[2] ? undefined : "Voer eerst een voltooide GEO/SEO-scan (fase 2) uit.",
        }}
        onSelect={(next) => {
          setPhase(next)
          // Tabbladen verschillen per fase: het tabblad begint opnieuw.
          writeUrlParams({ fase: String(next), tab: null })
        }}
      />
      <MondayBoardSetting customerId={customerId} />
      {phase === 1 && <NulmetingWorkspace customerId={customerId} onChange={refreshPhases} />}
      {phase === 2 && <GeoWorkspace customerId={customerId} onChange={refreshPhases} />}
      {phase === 3 && <ContentWorkspace customerId={customerId} onChange={refreshPhases} />}
    </div>
  )
}

function NulmetingWorkspace({ customerId, onChange }: { customerId: string; onChange: () => void }) {
  const [scans, setScans] = useState<LaunchScan[] | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [scan, setScan] = useState<LaunchScanDetail | null>(null)
  const [tab, setTabState] = useState<TabKey>(() => readUrlChoice("tab", TAB_KEYS, "overview"))
  const setTab = (next: TabKey) => {
    setTabState(next)
    writeUrlParams({ fase: "1", tab: next })
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
  usePolling(
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

  return (
    <div className="space-y-6">
      <section className="space-y-4 rounded-lg border bg-card p-4 sm:p-6">
        <div>
          <h2 className="text-lg font-bold tracking-wide text-primary">Fase 1 · Nulmeting &amp; AI scan</h2>
          <p className="text-sm text-muted-foreground">
            Haalt de sitemap op, maakt een site-inventaris (statuscodes, indexeerbaarheid, title/meta/H1, links,
            afbeeldingen, structured data), meet de Core Web Vitals per pagina (mobiel), controleert de
            AI-vindbaarheid en laat de Nulmeting-agent een rapport met actiepunten schrijven.
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <label className="space-y-1 text-sm">
            <span className="text-xs text-muted-foreground">Max. pagina&apos;s</span>
            <Input type="number" min={1} max={2000} value={maxPages} onChange={(e) => setMaxPages(Number(e.target.value) || 1)} className="w-28" />
          </label>
          <label className="space-y-1 text-sm">
            <span className="text-xs text-muted-foreground">Max. CWV-metingen</span>
            <Input type="number" min={0} max={500} value={vitalsMax} onChange={(e) => setVitalsMax(Math.max(0, Number(e.target.value) || 0))} className="w-28" />
          </label>
          <Button onClick={startScan} disabled={busy || anyRunning}>
            {busy ? <Loader2 className="animate-spin" /> : <Play />}
            {anyRunning ? "Scan loopt…" : "Start nieuwe scan"}
          </Button>
          {scans && scans.length > 0 && (
            <label className="ml-auto space-y-1 text-sm">
              <span className="text-xs text-muted-foreground">Scangeschiedenis</span>
              <select
                value={selectedId ?? ""}
                onChange={(e) => setSelectedId(e.target.value)}
                className="block h-9 rounded-md border bg-background px-2 text-sm"
              >
                {scans.map((s) => (
                  <option key={s.id} value={s.id}>
                    {formatDateTime(s.created_at)} · {STATUS_LABELS[s.status]}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
        {error && <p className="rounded-md border border-red-300 px-3 py-2 text-sm text-red-700">{error}</p>}
      </section>

      {scans && scans.length === 0 && (
        <p className="text-sm text-muted-foreground">Nog geen scans voor deze klant. Start de eerste scan hierboven.</p>
      )}

      {scan && (
        <section className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <ScanStatusBadge status={scan.status} />
            <span className="text-sm text-muted-foreground">
              Gestart {formatDateTime(scan.created_at)}
              {scan.completed_at && ` · klaar ${formatDateTime(scan.completed_at)}`}
            </span>
            <div className="ml-auto flex flex-wrap gap-2">
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
                  <Button size="sm" variant="ghost" onClick={deleteScan} disabled={busy}>
                    <Trash2 /> Verwijderen
                  </Button>
                </>
              )}
            </div>
          </div>

          {running && <ScanProgress scan={scan} />}
          {scan.status === "failed" && (
            <p className="rounded-md border border-red-300 px-3 py-2 text-sm text-red-700">
              Scan mislukt: {scan.error_message ?? "onbekende fout"}
            </p>
          )}

          {(scan.status === "completed" || scan.status === "analyzing" || scan.status === "vitals") && (
            <>
              <div className="flex gap-1 overflow-x-auto border-b">
                {TABS.map((t) => (
                  <button
                    key={t.key}
                    type="button"
                    onClick={() => setTab(t.key)}
                    className={cn(
                      "whitespace-nowrap border-b-2 px-4 py-2 text-sm transition-colors",
                      tab === t.key ? "border-primary font-medium text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"
                    )}
                  >
                    {t.label}
                    {t.key === "issues" && scan.summary_stats?.issues ? ` (${scan.summary_stats.issues.total})` : ""}
                  </button>
                ))}
              </div>
              {tab === "overview" && <OverviewTab scan={scan} />}
              {tab === "issues" && <IssuesTab scanId={scan.id} customerId={customerId} />}
              {tab === "inventory" && <InventoryTab scanId={scan.id} />}
              {tab === "vitals" && <VitalsTab scanId={scan.id} measuring={scan.status === "vitals"} />}
              {tab === "ai" && <AiChecksTab checks={scan.ai_checks} />}
            </>
          )}
        </section>
      )}
    </div>
  )
}
