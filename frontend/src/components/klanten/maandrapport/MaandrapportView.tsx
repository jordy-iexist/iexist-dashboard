"use client"

import { useEffect, useState } from "react"
import { CircleAlert, Download, Loader2, RefreshCw, RotateCcw, Send, Sparkles } from "lucide-react"

import { MonthPicker } from "@/components/klanten/maandrapport/MonthPicker"
import { ReportPreview } from "@/components/klanten/maandrapport/ReportPreview"
import { SectionsCard, SettingsCard, StatusCard } from "@/components/klanten/maandrapport/SideCards"
import { Pill } from "@/components/livegang/shared"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { usePolling } from "@/hooks/use-polling"
import {
  MonthlyReportError,
  fetchReport,
  isReportActive,
  monthLabel,
  regenerateReport,
  startReport,
  type MonthlyReport,
} from "@/lib/monthly-report"

export type MaandrapportViewProps = {
  customerId: string
  customerName: string
  domain: string
  /** "YYYY-MM"; al gecontroleerd door de pagina. */
  month: string
  /** null = de knop is uitgeschakeld (oudste maand). */
  previousMonth: string | null
  /** null = de knop is uitgeschakeld (lopende maand). */
  nextMonth: string | null
  formOfAddress: "je" | "u" | null
  toneOfVoice: string | null
}

const POLL_INTERVAL_MS = 3000

function errorMessage(err: unknown) {
  return err instanceof Error && err.message ? err.message : "Er ging iets mis."
}

function ErrorBlock({ children, action }: { children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center gap-3 rounded-md border border-red-300 bg-card px-3 py-2 text-sm text-red-700 dark:text-red-300"
    >
      <CircleAlert className="size-4 shrink-0" aria-hidden="true" />
      <span className="min-w-0 flex-1">{children}</span>
      {action}
    </div>
  )
}

/**
 * Maandrapport van één klant en maand (Figma 13 · Maandrapport).
 *
 * - Bij het openen wordt het rapport opgehaald; zonder rapport is de status `draft`.
 * - Zolang er een run loopt (`pending`/`collecting`/`writing`) wordt het elke 3 seconden ververst.
 * - "Genereren" start de eerste run; "Opnieuw genereren" haalt cijfers en tekst opnieuw op.
 * - Aanvragen invullen kan altijd, ook zonder rapport en tijdens een run.
 */
export function MaandrapportView({
  customerId,
  customerName,
  domain,
  month,
  previousMonth,
  nextMonth,
  formOfAddress,
  toneOfVoice,
}: MaandrapportViewProps) {
  const [report, setReport] = useState<MonthlyReport | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  useEffect(() => {
    let ignore = false
    fetchReport(customerId, month)
      .then((next) => {
        if (ignore) return
        setReport(next)
        setLoadError(null)
      })
      .catch((err: unknown) => {
        if (!ignore) setLoadError(errorMessage(err))
      })
    return () => {
      ignore = true
    }
  }, [customerId, month, attempt])

  const active = report !== null && isReportActive(report.status)

  const { failing } = usePolling(
    async () => {
      setReport(await fetchReport(customerId, month))
    },
    active,
    POLL_INTERVAL_MS
  )

  /** Eerste run vanuit `draft`, anders opnieuw (vanaf `completed` of `failed`). */
  async function generate() {
    if (!report) return
    setBusy(true)
    setActionError(null)
    try {
      setReport(
        report.status === "draft" ? await startReport(customerId, month) : await regenerateReport(customerId, month)
      )
    } catch (err) {
      // 409 = loopt al of bestaat al: dan alleen de actuele stand tonen.
      if (!(err instanceof MonthlyReportError && err.status === 409)) setActionError(errorMessage(err))
      const latest = await fetchReport(customerId, month).catch(() => null)
      if (latest) setReport(latest)
    } finally {
      setBusy(false)
    }
  }

  const label = monthLabel(month)
  const hasText = report?.report != null
  const regenerates = hasText || report?.status === "completed" || report?.status === "failed"
  const generateDisabled = !report || active || busy

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0 space-y-1">
          <p className="text-[13px] text-muted-foreground">
            Rapportage <span aria-hidden="true">/</span> {customerName}
          </p>
          <h1 className="text-2xl font-bold tracking-tight break-words sm:text-[28px]">Maandrapport {label}</h1>
          <p className="text-[13px] text-muted-foreground">
            Automatisch opgesteld door Claude uit Search Console, ProRankTracker en het uitgevoerde werk · in
            begrijpelijke taal voor de klant
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <MonthPicker customerId={customerId} month={month} previousMonth={previousMonth} nextMonth={nextMonth} />
          <span title={active ? "Er wordt al een rapport geschreven; wacht tot dat klaar is." : undefined}>
            <Button onClick={generate} disabled={generateDisabled}>
              {active || busy ? (
                <Loader2 className="animate-spin" aria-hidden="true" />
              ) : regenerates ? (
                <RefreshCw aria-hidden="true" />
              ) : (
                <Sparkles aria-hidden="true" />
              )}
              {regenerates ? "Opnieuw genereren" : "Genereren"}
            </Button>
          </span>
          <Pill>Binnenkort</Pill>
          {/* Een uitgeschakelde knop krijgt geen muisgebeurtenissen; de uitleg staat op de omhulling. */}
          <span title="Binnenkort">
            <Button variant="outline" disabled>
              <Download aria-hidden="true" />
              Download PDF
            </Button>
          </span>
          <span title="Binnenkort">
            <Button variant="outline" disabled>
              <Send aria-hidden="true" />
              Goedkeuren & klaarzetten
            </Button>
          </span>
        </div>
      </header>

      {actionError && <ErrorBlock>{actionError}</ErrorBlock>}

      {loadError && !report ? (
        <ErrorBlock
          action={
            <Button size="sm" variant="outline" onClick={() => setAttempt((value) => value + 1)}>
              <RotateCcw aria-hidden="true" />
              Opnieuw proberen
            </Button>
          }
        >
          Het maandrapport kon niet worden opgehaald: {loadError}
        </ErrorBlock>
      ) : (
        <div className="grid items-start gap-6 lg:grid-cols-[360px_minmax(0,1fr)]">
          <div className="space-y-6">
            <SettingsCard
              customerName={customerName}
              domain={domain}
              month={month}
              report={report}
              formOfAddress={formOfAddress}
              toneOfVoice={toneOfVoice}
            />
            <SectionsCard />
            <StatusCard report={report} failing={failing} busy={busy} onRetry={generate} />
          </div>

          {report ? (
            <ReportPreview
              customerId={customerId}
              customerName={customerName}
              month={month}
              report={report}
              busy={busy}
              onGenerate={generate}
              onLeadsSaved={setReport}
            />
          ) : (
            <div aria-busy="true" className="rounded-xl bg-muted p-4 sm:p-6">
              <p role="status" className="sr-only">
                Maandrapport laden…
              </p>
              <Skeleton className="h-[560px] w-full rounded-md bg-card" />
            </div>
          )}
        </div>
      )}
    </div>
  )
}
