"use client"

import ReactMarkdown from "react-markdown"
import { Bot, Check, Copy, Download, Loader2, Play, Printer, Square, Trash2 } from "lucide-react"
import Link from "next/link"
import { useCallback, useEffect, useRef, useState } from "react"

import { Button } from "@/components/ui/button"
import { ChecklistTab } from "@/components/livegang/ChecklistTab"
import { IssuesTab } from "@/components/livegang/IssuesTab"
import { ComparisonTab, QuarterlyItemDetails } from "@/components/livegang/QuarterlyDetails"
import { SearchConsoleSetting } from "@/components/livegang/SearchConsoleSetting"
import {
  isActive,
  PanelRow,
  PanelTabs,
  PercentRing,
  PhasePanel,
  Pill,
  QUARTERLY_STEPS,
  ScanProgress,
  ScanStatusBadge,
} from "@/components/livegang/shared"
import {
  API_BASE,
  apiFetch,
  formatDateTime,
  periodLabel,
  periodQuery,
  syncMondayLinks,
  type LaunchScan,
  type LaunchScanDetail,
  type QuarterlyChecklist,
} from "@/lib/launch-checklist"
import { usePolling } from "@/hooks/use-polling"
import { readUrlChoice, readUrlParam, writeUrlParams } from "@/lib/url-state"

const TABS = [
  { key: "checklist", label: "Checklist" },
  { key: "comparison", label: "Vergelijking" },
  { key: "issues", label: "Actiepunten" },
  { key: "report", label: "Rapportage" },
] as const

type TabKey = (typeof TABS)[number]["key"]
const TAB_KEYS = TABS.map((t) => t.key)
const PERIOD_PATTERN = /^\d{4}-Q[1-4]$/

function initialPeriod(): string | null {
  const value = readUrlParam("ronde")
  return value && PERIOD_PATTERN.test(value) ? value : null
}

export function QuarterlyWorkspace({ customerId, onChange }: { customerId: string; onChange: () => void }) {
  const [checklist, setChecklist] = useState<QuarterlyChecklist | null>(null)
  const [latest, setLatest] = useState<LaunchScanDetail | null>(null)
  const [report, setReport] = useState<LaunchScanDetail | null>(null)
  // null = de huidige ronde (die bepaalt de backend).
  const [period, setPeriodState] = useState<string | null>(initialPeriod)
  const [storedTab, setTabState] = useState<TabKey>(() => readUrlChoice("tab", TAB_KEYS, "checklist"))
  const [busy, setBusy] = useState(false)
  const [copied, setCopied] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const reportIdRef = useRef<string | null>(null)

  const setTab = (next: TabKey) => {
    setTabState(next)
    writeUrlParams({ fase: "4", tab: next })
  }
  const setPeriod = (next: string | null) => {
    setPeriodState(next)
    writeUrlParams({ fase: "4", ronde: next })
  }

  const loadChecklist = useCallback(async () => {
    const data = await apiFetch<QuarterlyChecklist>(`/customers/${customerId}/quarterly-checklist${periodQuery(period)}`)
    setChecklist(data)
    // Het rapport hoort bij de scan: alleen opnieuw ophalen als de scan wisselt.
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
  }, [customerId, period])

  const loadLatest = useCallback(async () => {
    const result = await apiFetch<{ items: LaunchScan[] }>(
      `/scans?customer_website_id=${encodeURIComponent(customerId)}&phase=4&limit=20`
    )
    const first = result.items.find((s) => s.phase === 4)
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
      await apiFetch<LaunchScanDetail>(`/customers/${customerId}/quarterly-scans`, { method: "POST" })
      // Een nieuwe scan hoort altijd bij de huidige ronde.
      if (period !== null) setPeriod(null)
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
    if (!latest || !window.confirm("Deze kwartaalscan verwijderen? Handmatige afvinkstatussen van de ronde blijven bewaard.")) return
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

  async function copyReport() {
    if (!report?.ai_summary) return
    try {
      await navigator.clipboard.writeText(report.ai_summary)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      setError("Kopiëren naar het klembord is mislukt.")
    }
  }

  const running = latest ? isActive(latest.status) : false
  const completedScan = checklist?.scan ?? null
  const viewingCurrent = !checklist || checklist.period === checklist.current_period
  const currentScanned = checklist?.periods.find((p) => p.period === checklist.current_period)?.scanned ?? false
  // Zonder voltooide scan in deze ronde is alleen de checklist beschikbaar.
  const tab: TabKey = completedScan ? storedTab : "checklist"

  return (
    <div className="space-y-4">
      <PhasePanel
        title="Fase 4 · Kwartaal GEO-werkzaamheden"
        description={
          <>
            Elk kwartaal een nieuwe ronde: herhaalt de nulmeting, controleert nieuwe pagina&apos;s op 404&apos;s en
            indexeerbaarheid, valideert alle JSON-LD en vergelijkt AI-vindbaarheid, actiepunten, posities en backlinks met
            de vorige ronde. Met de Search Console-koppeling komen daar klikken, vertoningen, sitemaps en de indexstatus
            van nieuwe pagina&apos;s bij. Daarna schrijft een AI-agent een conceptrapport. De afvinkstatus geldt per ronde.
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
                <p className="text-xs text-muted-foreground">punten afgerond in {checklist.period_label}</p>
              </div>
            </div>
          )
        }
      >
        <PanelRow className="space-y-3">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            {checklist && (
              <label className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground">Ronde</span>
                <select
                  value={checklist.period}
                  onChange={(e) => setPeriod(e.target.value === checklist.current_period ? null : e.target.value)}
                  className="h-8 rounded-md border bg-background px-2 text-sm"
                  disabled={running}
                >
                  {checklist.periods.map((option) => (
                    <option key={option.period} value={option.period}>
                      {option.label}
                      {option.period === checklist.current_period ? " (huidig)" : ""}
                      {option.scanned ? "" : " · niet gescand"}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {latest ? (
              <>
                <ScanStatusBadge status={latest.status} />
                <span className="text-muted-foreground">
                  {latest.status === "completed"
                    ? `Laatste scan ${formatDateTime(latest.completed_at ?? latest.created_at)} (${periodLabel(latest.period)})`
                    : `Gestart ${formatDateTime(latest.created_at)}`}
                </span>
              </>
            ) : (
              <span className="text-muted-foreground">Nog geen kwartaalscan.</span>
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
              {checklist && !running && (
                <Button size="sm" variant="outline" asChild>
                  <Link href={`/dashboard/livegang/${customerId}/checklist/print?fase=4&ronde=${checklist.period}`} target="_blank">
                    <Printer /> Printversie / PDF
                  </Link>
                </Button>
              )}
            </div>
          </div>
          {latest && running && <ScanProgress scan={latest} steps={QUARTERLY_STEPS} bare />}
          {latest?.status === "failed" && (
            <p className="text-red-700 dark:text-red-400">Scan mislukt: {latest.error_message ?? "onbekende fout"}</p>
          )}
        </PanelRow>

        <PanelRow tone="muted">
          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={startScan} disabled={busy || running}>
              {busy ? <Loader2 className="animate-spin" /> : <Play />}
              {running
                ? "Scan loopt…"
                : currentScanned
                  ? "Opnieuw scannen"
                  : `Start ronde ${checklist ? periodLabel(checklist.current_period) : ""}`.trim()}
            </Button>
            <p className="text-xs text-muted-foreground">
              {viewingCurrent
                ? "Opnieuw scannen na een wijziging (bijv. voor de schema-validatie) houdt de afvinkstatus van deze ronde."
                : `Je bekijkt een eerdere ronde. Een nieuwe scan hoort bij ${checklist ? periodLabel(checklist.current_period) : "de huidige ronde"}.`}
            </p>
          </div>
        </PanelRow>

        <PanelRow tone="muted">
          <SearchConsoleSetting customerId={customerId} />
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
                  Nog geen scan in {checklist.period_label}. Start een scan om de automatische punten te laten controleren;
                  handmatige punten kun je nu al afvinken.
                </p>
              )}
              <ChecklistTab
                key={checklist.period}
                checklist={checklist}
                customerId={customerId}
                path="quarterly-checklist"
                period={checklist.period}
                itemDetails={(item) => <QuarterlyItemDetails item={item} />}
                onChanged={loadChecklist}
              />
            </>
          )}
          {tab === "comparison" && completedScan && <ComparisonTab checklist={checklist} />}
          {tab === "issues" && completedScan && <IssuesTab scanId={completedScan.id} customerId={customerId} />}
          {tab === "report" && (
            <section className="space-y-3">
              <div className="flex flex-wrap items-center gap-3">
                <h3 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                  <Bot className="size-4" /> Conceptrapport {checklist.period_label} (AI-agent)
                </h3>
                {report?.ai_summary && (
                  <Button size="sm" variant="outline" className="ml-auto" onClick={() => void copyReport()}>
                    {copied ? <Check /> : <Copy />} {copied ? "Gekopieerd" : "Kopieer (Markdown)"}
                  </Button>
                )}
              </div>
              <p className="text-xs text-muted-foreground">
                {checklist.sources?.search_console
                  ? "Concept op basis van de scan, de SEO-tracker, Ahrefs en Search Console. Vul de cijfers uit GA4, Bing"
                  : "Concept op basis van de scan, de SEO-tracker en Ahrefs. Vul de cijfers uit Search Console, GA4, Bing"}{" "}
                Webmaster en ProRankTracker zelf aan en vink daarna &quot;Maandrapportage opstellen&quot; af.
              </p>
              {report?.ai_summary ? (
                <article className="prose prose-sm max-w-none rounded-lg border bg-card p-6 leading-7 dark:prose-invert">
                  <ReactMarkdown>{report.ai_summary}</ReactMarkdown>
                </article>
              ) : (
                <p className="text-sm text-muted-foreground">Er is geen conceptrapport gegenereerd (zie waarschuwingen).</p>
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
