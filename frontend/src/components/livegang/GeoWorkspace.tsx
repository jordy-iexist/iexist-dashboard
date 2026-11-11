"use client"

import ReactMarkdown from "react-markdown"
import { Bot, Download, Loader2, Play, Printer, Square, Trash2 } from "lucide-react"
import Link from "next/link"
import { useCallback, useEffect, useRef, useState } from "react"

import { Button } from "@/components/ui/button"
import { ChecklistTab } from "@/components/livegang/ChecklistTab"
import { IssuesTab } from "@/components/livegang/IssuesTab"
import { SchemaTab } from "@/components/livegang/SchemaTab"
import {
  GEO_STEPS,
  isActive,
  PercentRing,
  Pill,
  ScanProgress,
  ScanStatusBadge,
} from "@/components/livegang/shared"
import {
  API_BASE,
  apiFetch,
  formatDateTime,
  type Checklist,
  type LaunchScan,
  syncMondayLinks,
  type LaunchScanDetail,
} from "@/lib/launch-checklist"
import { usePolling } from "@/hooks/use-polling"
import { readUrlChoice, writeUrlParams } from "@/lib/url-state"
import { cn } from "@/lib/utils"

const TABS = [
  { key: "checklist", label: "Checklist" },
  { key: "schema", label: "Schema per paginatype" },
  { key: "issues", label: "Actiepunten" },
  { key: "report", label: "Rapport" },
] as const

type TabKey = (typeof TABS)[number]["key"]
const TAB_KEYS = TABS.map((t) => t.key)

export function GeoWorkspace({ customerId, onChange }: { customerId: string; onChange: () => void }) {
  const [checklist, setChecklist] = useState<Checklist | null>(null)
  const [latest, setLatest] = useState<LaunchScanDetail | null>(null)
  const [report, setReport] = useState<LaunchScanDetail | null>(null)
  const [storedTab, setTabState] = useState<TabKey>(() => readUrlChoice("tab", TAB_KEYS, "checklist"))
  const setTab = (next: TabKey) => {
    setTabState(next)
    writeUrlParams({ fase: "2", tab: next })
  }
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const reportIdRef = useRef<string | null>(null)

  const loadChecklist = useCallback(async () => {
    const data = await apiFetch<Checklist>(`/customers/${customerId}/checklist`)
    setChecklist(data)
    // Het rapport hoort bij de scan: alleen opnieuw ophalen als de scan wisselt,
    // niet bij elke afgevinkte regel.
    const scanId = data.scan?.id ?? null
    if (scanId === null) {
      reportIdRef.current = null
      setReport(null)
    } else if (reportIdRef.current !== scanId) {
      const detail = await apiFetch<LaunchScanDetail>(`/scans/${scanId}`)
      reportIdRef.current = scanId
      setReport(detail)
    }
    return data
  }, [customerId])

  const loadLatest = useCallback(async () => {
    const result = await apiFetch<{ items: LaunchScan[] }>(
      `/scans?customer_website_id=${encodeURIComponent(customerId)}&phase=2&limit=20`
    )
    const first = result.items.find((s) => s.phase === 2)
    const detail = first ? await apiFetch<LaunchScanDetail>(`/scans/${first.id}`) : null
    setLatest(detail)
    return detail
  }, [customerId])

  useEffect(() => {
    Promise.all([loadChecklist(), loadLatest()]).catch((err: Error) => setError(err.message))
  }, [loadChecklist, loadLatest])

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

  // Pollen zolang de laatste scan loopt; daarna checklist en fasestatus verversen.
  usePolling(
    async () => {
      const next = await loadLatest()
      if (!next || !isActive(next.status)) {
        await loadChecklist()
        onChange()
      }
    },
    latest !== null && isActive(latest.status),
    3000
  )

  async function startScan() {
    setBusy(true)
    setError(null)
    try {
      await apiFetch<LaunchScanDetail>(`/customers/${customerId}/geo-scans`, {
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
    if (!latest || !window.confirm("Deze GEO/SEO-scan verwijderen? Handmatige afvinkstatussen blijven bewaard.")) return
    setBusy(true)
    try {
      await apiFetch(`/scans/${latest.id}`, { method: "DELETE" })
      await Promise.all([loadLatest(), loadChecklist()])
      onChange()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function setWebshop(value: string) {
    const is_webshop = value === "auto" ? null : value === "ja"
    try {
      setChecklist(
        await apiFetch<Checklist>(`/customers/${customerId}/webshop`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ is_webshop }),
        })
      )
    } catch (err) {
      setError((err as Error).message)
    }
  }

  const running = latest ? isActive(latest.status) : false
  const completedScan = checklist?.scan ?? null
  // Zonder voltooide scan is alleen de checklist beschikbaar.
  const tab: TabKey = completedScan ? storedTab : "checklist"

  return (
    <div className="space-y-6">
      <section className="space-y-4 rounded-lg border bg-card p-4 sm:p-6">
        <div className="flex flex-wrap items-start gap-4">
          <div className="min-w-0 flex-1 space-y-1">
            <h2 className="text-lg font-bold tracking-wide text-primary">Fase 2 · GEO/SEO-checklist</h2>
            <p className="text-sm text-muted-foreground">
              Bouwt voort op de laatste nulmeting: controleert schema.org per paginatype, entiteit- en
              vertrouwenssignalen (NAP, sameAs, KvK/BTW), crawlbaarheid (canonicals, klikdiepte, verweesde
              pagina&apos;s) en AI-toegang (robots.txt, CDN/Cloudflare, llms.txt). Handmatige punten vink je hier
              af; die status blijft per klant bewaard.
            </p>
          </div>
          {checklist && (
            <div className="flex items-center gap-3">
              <PercentRing percent={checklist.percent} size={64} />
              <div className="text-sm">
                <p className="font-medium">
                  {checklist.done} / {checklist.total} afgerond
                </p>
                <p className="text-xs text-muted-foreground">
                  {completedScan ? `Gescand ${formatDateTime(completedScan.completed_at)}` : "Nog niet gescand"}
                </p>
              </div>
            </div>
          )}
        </div>

        <div className="flex flex-wrap items-end gap-3">
          <Button onClick={startScan} disabled={busy || running}>
            {busy ? <Loader2 className="animate-spin" /> : <Play />}
            {running ? "Scan loopt…" : completedScan ? "Opnieuw scannen" : "Start GEO/SEO-scan"}
          </Button>
          {checklist && (
            <label className="space-y-1 text-sm">
              <span className="text-xs text-muted-foreground">Webshop</span>
              <select
                value={checklist.webshop_override === null ? "auto" : checklist.webshop_override ? "ja" : "nee"}
                onChange={(e) => void setWebshop(e.target.value)}
                className="block h-9 rounded-md border bg-background px-2 text-sm"
                title={checklist.webshop_reasons.join(", ") || undefined}
              >
                <option value="auto">
                  Automatisch ({checklist.webshop_detected === null ? "nog niet gescand" : checklist.webshop_detected ? "webshop" : "geen webshop"})
                </option>
                <option value="ja">Ja, webshop</option>
                <option value="nee">Geen webshop</option>
              </select>
            </label>
          )}
          <div className="ml-auto flex flex-wrap gap-2">
            {completedScan && (
              <Button size="sm" variant="outline" asChild>
                <a href={`${API_BASE}/scans/${completedScan.id}/export?kind=checklist`}>
                  <Download /> Checklist (CSV)
                </a>
              </Button>
            )}
            <Button size="sm" variant="outline" asChild>
              <Link href={`/dashboard/livegang/${customerId}/checklist/print`} target="_blank">
                <Printer /> Printversie / PDF
              </Link>
            </Button>
          </div>
        </div>
        {error && <p className="rounded-md border border-red-300 px-3 py-2 text-sm text-red-700">{error}</p>}
      </section>

      {latest && (running || latest.status === "failed" || latest.status === "canceled") && (
        <section className="space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <ScanStatusBadge status={latest.status} />
            <span className="text-sm text-muted-foreground">Gestart {formatDateTime(latest.created_at)}</span>
            <div className="ml-auto flex gap-2">
              {running ? (
                <Button size="sm" variant="ghost" onClick={cancelScan} disabled={busy}>
                  <Square /> Annuleren
                </Button>
              ) : (
                <Button size="sm" variant="ghost" onClick={deleteScan} disabled={busy}>
                  <Trash2 /> Verwijderen
                </Button>
              )}
            </div>
          </div>
          {running && <ScanProgress scan={latest} steps={GEO_STEPS} />}
          {latest.status === "failed" && (
            <p className="rounded-md border border-red-300 px-3 py-2 text-sm text-red-700">
              Scan mislukt: {latest.error_message ?? "onbekende fout"}
            </p>
          )}
        </section>
      )}

      {report?.warnings && report.warnings.length > 0 && (
        <ul className="space-y-1 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:bg-amber-900/20 dark:text-amber-200">
          {report.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}

      {checklist && (
        <section className="space-y-4">
          <div className="flex gap-1 overflow-x-auto border-b">
            {TABS.map((t) => {
              const disabled = t.key !== "checklist" && !completedScan
              return (
                <button
                  key={t.key}
                  type="button"
                  disabled={disabled}
                  onClick={() => setTab(t.key)}
                  className={cn(
                    "whitespace-nowrap border-b-2 px-4 py-2 text-sm transition-colors",
                    tab === t.key ? "border-primary font-medium text-foreground" : "border-transparent text-muted-foreground hover:text-foreground",
                    disabled && "cursor-not-allowed opacity-50 hover:text-muted-foreground"
                  )}
                >
                  {t.label}
                </button>
              )
            })}
          </div>

          {tab === "checklist" && (
            <>
              {!completedScan && (
                <p className="text-sm text-muted-foreground">
                  Nog geen GEO/SEO-scan. Start een scan om de automatische punten te laten controleren; handmatige
                  punten kun je nu al afvinken.
                </p>
              )}
              <ChecklistTab checklist={checklist} customerId={customerId} onChanged={loadChecklist} />
            </>
          )}
          {tab === "schema" && completedScan && checklist.source_scan_id && (
            <SchemaTab
              geoScanId={completedScan.id}
              sourceScanId={checklist.source_scan_id}
              pageTypes={checklist.page_types}
              onChanged={loadChecklist}
            />
          )}
          {tab === "issues" && completedScan && <IssuesTab scanId={completedScan.id} customerId={customerId} />}
          {tab === "report" && (
            <section className="space-y-3">
              <h3 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                <Bot className="size-4" /> GEO/SEO-rapport (AI-agent)
              </h3>
              {report?.ai_summary ? (
                <article className="prose prose-sm max-w-none rounded-lg border bg-card p-6 leading-7 dark:prose-invert">
                  <ReactMarkdown>{report.ai_summary}</ReactMarkdown>
                </article>
              ) : (
                <p className="text-sm text-muted-foreground">Er is geen AI-rapport gegenereerd (zie waarschuwingen).</p>
              )}
              {report?.agent_trace?.steps && (
                <p className="text-xs text-muted-foreground">
                  <Pill>{report.agent_trace.model}</Pill> {report.agent_trace.steps.length} tool-aanroepen ·{" "}
                  {(report.agent_trace.usage?.input_tokens ?? 0) + (report.agent_trace.usage?.output_tokens ?? 0)} tokens
                </p>
              )}
            </section>
          )}
        </section>
      )}
    </div>
  )
}
