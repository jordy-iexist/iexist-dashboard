"use client"

import ReactMarkdown from "react-markdown"
import { Bot, Download, Loader2, Play, Printer, Square, Trash2 } from "lucide-react"
import Link from "next/link"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import { Button } from "@/components/ui/button"
import { ChecklistTab, type ChecklistItemAction } from "@/components/livegang/ChecklistTab"
import { ContentGapTab } from "@/components/livegang/ContentGapTab"
import { ContentPagesTab } from "@/components/livegang/ContentPagesTab"
import { IssuesTab } from "@/components/livegang/IssuesTab"
import {
  CONTENT_STEPS,
  isActive,
  PercentRing,
  Pill,
  ScanProgress,
  ScanStatusBadge,
  StatTile,
} from "@/components/livegang/shared"
import {
  API_BASE,
  apiFetch,
  formatDateTime,
  syncMondayLinks,
  type ChecklistItem,
  type ContentChecklist,
  type LaunchScan,
  type LaunchScanDetail,
  type ScanStatus,
} from "@/lib/launch-checklist"
import { usePolling } from "@/hooks/use-polling"
import { readUrlChoice, writeUrlParams } from "@/lib/url-state"
import { cn } from "@/lib/utils"

const TABS = [
  { key: "checklist", label: "Checklist" },
  { key: "pages", label: "Pagina's & voorstellen" },
  { key: "new", label: "Nieuwe content" },
  { key: "issues", label: "Actiepunten" },
  { key: "report", label: "Rapport" },
] as const

type TabKey = (typeof TABS)[number]["key"]
const TAB_KEYS = TABS.map((t) => t.key)
const ANALYSIS_STEPS: ScanStatus[] = ["analyzing"]

export function ContentWorkspace({ customerId, onChange }: { customerId: string; onChange: () => void }) {
  const [checklist, setChecklist] = useState<ContentChecklist | null>(null)
  const [latest, setLatest] = useState<LaunchScanDetail | null>(null)
  const [report, setReport] = useState<LaunchScanDetail | null>(null)
  const [storedTab, setTabState] = useState<TabKey>(() => readUrlChoice("tab", TAB_KEYS, "checklist"))
  const setTab = (next: TabKey) => {
    setTabState(next)
    writeUrlParams({ fase: "3", tab: next })
  }
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Verhoogt na elke afgeronde scan/analyse, zodat de tabbladen hun data herladen.
  const [refreshKey, setRefreshKey] = useState(0)
  const reportKeyRef = useRef<string | null>(null)
  // Checklistpunt waar de gebruiker vanuit de checklist op doorklikte.
  const [focusItem, setFocusItem] = useState<string | null>(null)

  const loadChecklist = useCallback(async () => {
    const data = await apiFetch<ContentChecklist>(`/customers/${customerId}/content-checklist`)
    setChecklist(data)
    // Rapport en waarschuwingen horen bij de scan en wijzigen na elke AI-analyse.
    const key = data.scan ? `${data.scan.id}:${data.scan.updated_at}` : null
    if (key === null) {
      reportKeyRef.current = null
      setReport(null)
    } else if (reportKeyRef.current !== key) {
      const detail = await apiFetch<LaunchScanDetail>(`/scans/${data.scan!.id}`)
      reportKeyRef.current = key
      setReport(detail)
    }
    return data
  }, [customerId])

  const loadLatest = useCallback(async () => {
    const result = await apiFetch<{ items: LaunchScan[] }>(
      `/scans?customer_website_id=${encodeURIComponent(customerId)}&phase=3&limit=20`
    )
    const first = result.items.find((s) => s.phase === 3)
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

  // Pollen zolang de scan of de AI-analyse loopt; daarna alles verversen.
  usePolling(
    async () => {
      const next = await loadLatest()
      if (!next || !isActive(next.status)) {
        await loadChecklist()
        setRefreshKey((k) => k + 1)
        onChange()
      }
    },
    latest !== null && isActive(latest.status),
    3000
  )

  async function run(action: () => Promise<unknown>) {
    setBusy(true)
    setError(null)
    try {
      await action()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const startScan = () =>
    run(async () => {
      if (
        checklist?.scan &&
        !window.confirm(
          "Opnieuw scannen? De site wordt opnieuw opgehaald en de checklist begint met een nieuwe scan. " +
            "AI-voorstellen van de huidige scan worden niet meegenomen; handmatige afvinkstatussen blijven bewaard."
        )
      )
        return
      await apiFetch<LaunchScanDetail>(`/customers/${customerId}/content-scans`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      })
      await loadLatest()
    })

  const cancelScan = () =>
    run(async () => {
      if (!latest) return
      await apiFetch(`/scans/${latest.id}/cancel`, { method: "POST" })
      await Promise.all([loadLatest(), loadChecklist()])
      setRefreshKey((k) => k + 1)
    })

  const deleteScan = () =>
    run(async () => {
      if (!latest || !window.confirm("Deze content-scan verwijderen? Handmatige afvinkstatussen blijven bewaard.")) return
      await apiFetch(`/scans/${latest.id}`, { method: "DELETE" })
      await Promise.all([loadLatest(), loadChecklist()])
      onChange()
    })

  const scan = checklist?.scan ?? null

  // Geen try/catch: de aanroepende tab toont de foutmelding.
  const startAnalysis = useCallback(
    async (pageIds: string[], runGap: boolean) => {
      if (!scan) return
      await apiFetch<LaunchScanDetail>(`/scans/${scan.id}/content-analysis`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ page_ids: pageIds, run_gap: runGap }),
      })
      await loadLatest()
    },
    [scan, loadLatest]
  )

  const itemLabels = useMemo(
    () =>
      Object.fromEntries(
        (checklist?.sections ?? []).flatMap((s) => s.items).map((i) => [i.key, i.label])
      ) as Record<string, string>,
    [checklist]
  )

  // Vanuit een checklistpunt naar de plek waar de voorstellen of pagina's staan.
  function itemAction(item: ChecklistItem): ChecklistItemAction | null {
    if (!scan || item.mode === "manual") return null
    const details = (item.auto?.details ?? {}) as { suggestions?: number; with_problems?: number }
    const section = checklist?.sections.find((s) => s.items.some((i) => i.key === item.key))?.key
    if (section === "nieuw") {
      return {
        label: details.suggestions ? `Bekijk ${details.suggestions} voorstellen` : "Naar nieuwe content",
        onClick: () => {
          setFocusItem(item.key)
          setTab("new")
        },
      }
    }
    if (!details.with_problems) return null
    return {
      label: `Bekijk ${details.with_problems} pagina's`,
      onClick: () => {
        setFocusItem(item.key)
        setTab("pages")
      },
    }
  }

  const running = latest ? isActive(latest.status) : false
  // De AI-analyse draait op een al voltooide scan: de resultaten blijven zichtbaar.
  const analysing = running && latest?.status === "analyzing" && latest.id === scan?.id
  const scanning = running && !analysing
  // Zonder scan is alleen de checklist beschikbaar.
  const tab: TabKey = scan ? storedTab : "checklist"
  const summary = checklist?.summary ?? null
  const usage = report?.agent_trace?.analysis_usage

  return (
    <div className="space-y-6">
      <section className="space-y-4 rounded-lg border bg-card p-4 sm:p-6">
        <div className="flex flex-wrap items-start gap-4">
          <div className="min-w-0 flex-1 space-y-1">
            <h2 className="text-lg font-bold tracking-wide text-primary">Fase 3 · Contentcreatie &amp; onpage optimalisatie</h2>
            <p className="text-sm text-muted-foreground">
              Stap 1: de scan haalt alle pagina&apos;s opnieuw op en controleert meta titels en descriptions (tekens en
              pixels), koppen, scanbaarheid, FAQ, afbeeldingen, interne links en of de bevindingen uit fase 1 zijn
              verwerkt. Stap 2: jij kiest de pagina&apos;s waarvoor de AI-agents concrete herschrijfvoorstellen maken en
              krijgt voorstellen voor nieuwe content.
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
                  {scan ? `Gescand ${formatDateTime(scan.completed_at ?? scan.created_at)}` : "Nog niet gescand"}
                </p>
              </div>
            </div>
          )}
        </div>

        <div className="flex flex-wrap items-end gap-3">
          <Button onClick={() => void startScan()} disabled={busy || running}>
            {busy ? <Loader2 className="animate-spin" /> : <Play />}
            {scanning ? "Scan loopt…" : scan ? "Opnieuw scannen" : "Start content-scan"}
          </Button>
          <div className="ml-auto flex flex-wrap gap-2">
            {scan && (
              <>
                <Button size="sm" variant="outline" asChild>
                  <a href={`${API_BASE}/scans/${scan.id}/export?kind=checklist`}>
                    <Download /> Checklist (CSV)
                  </a>
                </Button>
                <Button size="sm" variant="outline" asChild>
                  <a href={`${API_BASE}/scans/${scan.id}/export?kind=suggestions`}>
                    <Download /> Voorstellen (CSV)
                  </a>
                </Button>
              </>
            )}
            <Button size="sm" variant="outline" asChild>
              <Link href={`/dashboard/livegang/${customerId}/checklist/print?fase=3`} target="_blank">
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
            <span className="text-sm text-muted-foreground">
              {analysing ? "AI-analyse van de geselecteerde pagina's" : `Gestart ${formatDateTime(latest.created_at)}`}
            </span>
            <div className="ml-auto flex gap-2">
              {running ? (
                <Button size="sm" variant="ghost" onClick={() => void cancelScan()} disabled={busy}>
                  <Square /> {analysing ? "Analyse stoppen" : "Annuleren"}
                </Button>
              ) : (
                <Button size="sm" variant="ghost" onClick={() => void deleteScan()} disabled={busy}>
                  <Trash2 /> Verwijderen
                </Button>
              )}
            </div>
          </div>
          {running && <ScanProgress scan={latest} steps={analysing ? ANALYSIS_STEPS : CONTENT_STEPS} />}
          {latest.status === "failed" && (
            <p className="rounded-md border border-red-300 px-3 py-2 text-sm text-red-700">
              Scan mislukt: {latest.error_message ?? "onbekende fout"}
            </p>
          )}
        </section>
      )}

      {scan && summary && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatTile label="Pagina's gescand" value={summary.pages_fetched} />
          <StatTile label="Met verbeterpunten" value={summary.pages_with_problems} />
          <StatTile label="Door AI geanalyseerd" value={summary.pages_analysed} />
          <StatTile label="Open AI-voorstellen" value={summary.suggestions_open} />
        </div>
      )}

      {report?.warnings && report.warnings.length > 0 && (
        <ul className="space-y-1 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:bg-amber-900/20 dark:text-amber-200">
          {report.warnings.map((w, index) => (
            <li key={`${index}-${w}`}>{w}</li>
          ))}
        </ul>
      )}

      {checklist && (
        <section className="space-y-4">
          <div className="flex gap-1 overflow-x-auto border-b">
            {TABS.map((t) => {
              const disabled = t.key !== "checklist" && !scan
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
              {!scan && (
                <p className="text-sm text-muted-foreground">
                  Nog geen content-scan. Start een scan om de automatische punten te laten controleren; handmatige
                  punten kun je nu al afvinken.
                </p>
              )}
              <ChecklistTab
                checklist={checklist}
                customerId={customerId}
                path="content-checklist"
                itemAction={itemAction}
                onChanged={loadChecklist}
              />
            </>
          )}
          {tab === "pages" && scan && (
            <ContentPagesTab
              scanId={scan.id}
              itemLabels={itemLabels}
              analysing={running}
              gapAnalysed={Boolean(checklist.gap_analyzed_at)}
              maxPages={checklist.max_pages_per_analysis}
              refreshKey={refreshKey}
              itemFilter={focusItem}
              onClearItemFilter={() => setFocusItem(null)}
              onStart={startAnalysis}
              onChanged={loadChecklist}
            />
          )}
          {tab === "new" && scan && (
            <ContentGapTab
              scanId={scan.id}
              analysed={Boolean(checklist.gap_analyzed_at)}
              analysing={running}
              refreshKey={refreshKey}
              focusKey={focusItem}
              onRun={() => startAnalysis([], true)}
              onChanged={loadChecklist}
            />
          )}
          {tab === "issues" && scan && <IssuesTab key={refreshKey} scanId={scan.id} customerId={customerId} />}
          {tab === "report" && (
            <section className="space-y-3">
              <h3 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                <Bot className="size-4" /> Rapport content &amp; onpage (AI-agent)
              </h3>
              {report?.ai_summary ? (
                <article className="prose prose-sm max-w-none rounded-lg border bg-card p-6 leading-7 dark:prose-invert">
                  <ReactMarkdown>{report.ai_summary}</ReactMarkdown>
                </article>
              ) : (
                <p className="text-sm text-muted-foreground">
                  Het rapport wordt geschreven na de eerste AI-analyse (tabblad Pagina&apos;s &amp; voorstellen).
                </p>
              )}
              {usage && (
                <p className="text-xs text-muted-foreground">
                  {report?.agent_trace?.model && <Pill>{report.agent_trace.model}</Pill>} {usage.calls} AI-aanroepen ·{" "}
                  {(usage.input_tokens + usage.output_tokens).toLocaleString("nl-NL")} tokens (alle analyses van deze scan)
                </p>
              )}
            </section>
          )}
        </section>
      )}
    </div>
  )
}
