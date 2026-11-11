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
  PanelRow,
  PanelTabs,
  PercentRing,
  PhasePanel,
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
    <div className="space-y-4">
      <PhasePanel
        title="Fase 2 · GEO/SEO-checklist"
        description={
          <>
            Bouwt voort op de laatste nulmeting: controleert schema.org per paginatype, entiteit- en
            vertrouwenssignalen (NAP, sameAs, KvK/BTW), crawlbaarheid (canonicals, klikdiepte, verweesde
            pagina&apos;s) en AI-toegang (robots.txt, CDN/Cloudflare, llms.txt). Handmatige punten vink je hier
            af; die status blijft per klant bewaard.
          </>
        }
        aside={
          checklist &&
          !running && (
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
              {completedScan && !running && (
                <Button size="sm" variant="outline" asChild>
                  <a href={`${API_BASE}/scans/${completedScan.id}/export?kind=checklist`}>
                    <Download /> Checklist (CSV)
                  </a>
                </Button>
              )}
              {!running && (
                <Button size="sm" variant="outline" asChild>
                  <Link href={`/dashboard/livegang/${customerId}/checklist/print`} target="_blank">
                    <Printer /> Printversie / PDF
                  </Link>
                </Button>
              )}
            </div>
          </div>
          {latest && running && <ScanProgress scan={latest} steps={GEO_STEPS} bare />}
          {latest?.status === "failed" && (
            <p className="text-red-700 dark:text-red-400">Scan mislukt: {latest.error_message ?? "onbekende fout"}</p>
          )}
        </PanelRow>

        <PanelRow tone="muted">
          <div className="flex flex-wrap items-end gap-3">
            <Button onClick={startScan} disabled={busy || running}>
              {busy ? <Loader2 className="animate-spin" /> : <Play />}
              {running ? "Scan loopt…" : completedScan ? "Opnieuw scannen" : "Start GEO/SEO-scan"}
            </Button>
            {checklist && (
              <label className="space-y-1">
                <span className="block text-xs text-muted-foreground">Webshop</span>
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
          </div>
        </PanelRow>

        {!running && report?.warnings && report.warnings.length > 0 && (
          <PanelRow tone="warning">
            <ul className="space-y-1 text-xs">
              {report.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          </PanelRow>
        )}

        {error && <PanelRow tone="error">{error}</PanelRow>}

        {checklist && !running && (
          <PanelTabs
            tabs={TABS.map((t) => ({ key: t.key, label: t.label, disabled: t.key !== "checklist" && !completedScan }))}
            active={tab}
            onSelect={setTab}
          />
        )}
      </PhasePanel>

      {/* Tijdens een nieuwe scan horen de resultaten van de vorige scan niet in beeld. */}
      {running && (
        <p className="text-sm text-muted-foreground">
          Nieuwe scan loopt — de resultaten verschijnen hier zodra de scan klaar is.
        </p>
      )}

      {checklist && !running && (
        <section className="space-y-4">
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
