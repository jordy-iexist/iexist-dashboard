"use client"

import { Download, Loader2, Play, Square, Trash2 } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { AiChecksTab } from "@/components/livegang/AiChecksTab"
import { InventoryTab } from "@/components/livegang/InventoryTab"
import { IssuesTab } from "@/components/livegang/IssuesTab"
import { OverviewTab } from "@/components/livegang/OverviewTab"
import { PhaseStepper, ProgressBar, ScanStatusBadge } from "@/components/livegang/shared"
import { VitalsTab } from "@/components/livegang/VitalsTab"
import {
  ACTIVE_STATUSES,
  API_BASE,
  apiFetch,
  formatDateTime,
  STATUS_LABELS,
  type LaunchScan,
  type LaunchScanDetail,
  type ScanStatus,
} from "@/lib/launch-checklist"
import { cn } from "@/lib/utils"

const TABS = [
  { key: "overview", label: "Overzicht" },
  { key: "issues", label: "Actiepunten" },
  { key: "inventory", label: "Inventaris" },
  { key: "vitals", label: "Core Web Vitals" },
  { key: "ai", label: "AI-vindbaarheid" },
] as const

type TabKey = (typeof TABS)[number]["key"]

const STEPS: ScanStatus[] = ["discovering", "inventory", "vitals", "analyzing"]

function isActive(status: ScanStatus) {
  return ACTIVE_STATUSES.includes(status)
}

function ScanProgress({ scan }: { scan: LaunchScanDetail }) {
  const currentIndex = STEPS.indexOf(scan.status)
  let value = 0
  let max = 0
  let detail = ""
  if (scan.status === "inventory") {
    value = scan.inventoried_urls
    max = scan.total_urls
    detail = max ? `${value} / ${max} URL's` : `${value} URL's gecrawld`
  } else if (scan.status === "vitals") {
    value = scan.vitals_measured
    max = scan.vitals_total
    detail = `${value} / ${max} pagina's gemeten`
  }

  return (
    <div className="space-y-3 rounded-lg border bg-card p-4">
      <div className="flex items-center gap-2 text-sm font-medium">
        <Loader2 className="size-4 animate-spin text-primary" />
        {STATUS_LABELS[scan.status]}
        {detail && <span className="font-normal text-muted-foreground">· {detail}</span>}
      </div>
      <ProgressBar value={value} max={max} />
      <ol className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        {STEPS.map((step, index) => (
          <li
            key={step}
            className={cn(
              index < currentIndex && "text-green-700 dark:text-green-400",
              index === currentIndex && "font-semibold text-foreground"
            )}
          >
            {index + 1}. {STATUS_LABELS[step]}
          </li>
        ))}
      </ol>
    </div>
  )
}

export function LaunchScanWorkspace({ customerId }: { customerId: string }) {
  const [scans, setScans] = useState<LaunchScan[] | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [scan, setScan] = useState<LaunchScanDetail | null>(null)
  const [tab, setTab] = useState<TabKey>("overview")
  const [maxPages, setMaxPages] = useState(500)
  const [vitalsMax, setVitalsMax] = useState(100)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const loadScans = useCallback(async () => {
    const result = await apiFetch<{ items: LaunchScan[] }>(
      `/scans?customer_website_id=${encodeURIComponent(customerId)}&limit=20`
    )
    setScans(result.items)
    return result.items
  }, [customerId])

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

  // Detail laden + pollen zolang de scan loopt.
  useEffect(() => {
    if (pollRef.current) clearInterval(pollRef.current)
    if (!selectedId) {
      setScan(null)
      return
    }
    let cancelled = false
    loadScan(selectedId)
      .then((detail) => {
        if (cancelled || !isActive(detail.status)) return
        pollRef.current = setInterval(async () => {
          try {
            const next = await loadScan(selectedId)
            if (!isActive(next.status)) {
              if (pollRef.current) clearInterval(pollRef.current)
              void loadScans()
            }
          } catch {
            // tijdelijke fout: volgende poll opnieuw
          }
        }, 3000)
      })
      .catch((err: Error) => setError(err.message))
    return () => {
      cancelled = true
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [selectedId, loadScan, loadScans])

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
      <PhaseStepper completed={scan?.status === "completed"} />

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
                    {t.key === "issues" && scan.summary_stats ? ` (${scan.summary_stats.issues.total})` : ""}
                  </button>
                ))}
              </div>
              {tab === "overview" && <OverviewTab scan={scan} />}
              {tab === "issues" && <IssuesTab scanId={scan.id} />}
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
