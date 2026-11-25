import { Check, CircleAlert, Loader2, RotateCcw, X } from "lucide-react"

import { formatUsd, ResultCard } from "@/components/klanten/analyses/result-parts"
import { Pill, PollingFailedNotice } from "@/components/livegang/shared"
import { Button } from "@/components/ui/button"
import { modelLabel } from "@/lib/content-brief"
import { formatDayMonth, isReportActive, periodLabel, type MonthlyReport } from "@/lib/monthly-report"
import { cn } from "@/lib/utils"

const dateTimeFormat = new Intl.DateTimeFormat("nl-NL", {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Europe/Amsterdam",
})

function formatDateTime(value: string | null | undefined) {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : dateTimeFormat.format(date)
}

// --- Instellingen ---------------------------------------------------------------------------

function SettingRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[110px_minmax(0,1fr)] items-baseline gap-3 border-b py-2.5 text-[13px] first:pt-0 last:border-b-0 last:pb-0">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 font-medium break-words">{children}</dd>
    </div>
  )
}

export function SettingsCard({
  customerName,
  domain,
  month,
  report,
  formOfAddress,
  toneOfVoice,
}: {
  customerName: string
  domain: string
  month: string
  report: MonthlyReport | null
  formOfAddress: "je" | "u" | null
  toneOfVoice: string | null
}) {
  const tone = toneOfVoice?.trim()
  return (
    <ResultCard id="maandrapport-instellingen" title="Instellingen">
      <dl>
        <SettingRow label="Klant">
          {customerName}
          {domain && <span className="mt-0.5 block text-xs font-normal break-all text-muted-foreground">{domain}</span>}
        </SettingRow>
        <SettingRow label="Periode">{periodLabel(report?.data?.period, month)}</SettingRow>
        <SettingRow label="Toon">
          {/* Zonder aanspreekvorm in het klantprofiel schrijft Claude in de u-vorm. */}
          Begrijpelijk, geen jargon · {formOfAddress === "je" ? "je-vorm" : formOfAddress === "u" ? "u-vorm" : "u-vorm (standaard)"}
          {tone && (
            <span className="mt-0.5 line-clamp-2 block text-xs font-normal text-muted-foreground" title={tone}>
              {tone}
            </span>
          )}
        </SettingRow>
        <SettingRow label="Ontvanger">
          <Pill>Binnenkort</Pill>
        </SettingRow>
        <SettingRow label="Opmaak">
          <Pill>Binnenkort</Pill>
        </SettingRow>
      </dl>
    </ResultCard>
  )
}

// --- Onderdelen -----------------------------------------------------------------------------

/** Volgorde uit het ontwerp; `ready` = staat in deze versie in het rapport. */
const SECTIONS: { label: string; ready: boolean }[] = [
  { label: "Samenvatting", ready: true },
  { label: "Posities & klikken", ready: false },
  { label: "Uitgevoerde werkzaamheden", ready: true },
  { label: "Resultaten per wijziging", ready: false },
  { label: "AI-zichtbaarheid", ready: false },
  { label: "Plan volgende maand", ready: true },
  { label: "Uren & kosten", ready: false },
]

export function SectionsCard() {
  return (
    <ResultCard id="maandrapport-onderdelen" title="Onderdelen">
      <ul className="space-y-2.5">
        {SECTIONS.map((section) => (
          <li key={section.label} className="flex items-center gap-2.5 text-[13px]">
            <span
              aria-hidden="true"
              className={cn(
                "flex size-4 shrink-0 items-center justify-center rounded-[4px]",
                section.ready ? "bg-primary text-primary-foreground" : "border border-input bg-card"
              )}
            >
              {section.ready && <Check className="size-3" strokeWidth={3} />}
            </span>
            <span className={cn("min-w-0 flex-1", section.ready ? "font-medium" : "text-muted-foreground")}>
              {section.label}
              <span className="sr-only">{section.ready ? " (in het rapport)" : " (nog niet in het rapport)"}</span>
            </span>
            {!section.ready && <Pill>Binnenkort</Pill>}
          </li>
        ))}
      </ul>
    </ResultCard>
  )
}

// --- Status ---------------------------------------------------------------------------------

type StepState = "done" | "running" | "failed" | "current" | "todo"

const STEP_STATE_TEXT: Record<StepState, string> = {
  done: "klaar",
  running: "bezig",
  failed: "mislukt",
  current: "huidige stap",
  todo: "nog niet",
}

function StepDot({ state, number }: { state: StepState; number: number }) {
  const base = "flex size-5 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold"
  if (state === "done") {
    return (
      <span className={cn(base, "bg-status-good text-white")}>
        <Check className="size-3" strokeWidth={3} aria-hidden="true" />
      </span>
    )
  }
  if (state === "running") {
    return (
      <span className={cn(base, "border border-input text-muted-foreground")}>
        <Loader2 className="size-3 animate-spin" aria-hidden="true" />
      </span>
    )
  }
  if (state === "failed") {
    return (
      <span className={cn(base, "bg-status-critical text-white")}>
        <X className="size-3" strokeWidth={3} aria-hidden="true" />
      </span>
    )
  }
  if (state === "current") {
    return <span className={cn(base, "bg-primary text-primary-foreground")}>{number}</span>
  }
  return <span className={cn(base, "bg-muted text-muted-foreground")}>{number}</span>
}

function Step({
  number,
  label,
  state,
  children,
}: {
  number: number
  label: string
  state: StepState
  children?: React.ReactNode
}) {
  return (
    <li className="flex gap-2.5">
      <StepDot state={state} number={number} />
      <div className="min-w-0 flex-1 space-y-1">
        <p
          className={cn(
            "text-[13px] leading-5",
            state === "current" && "font-semibold",
            state === "todo" && "text-muted-foreground",
            (state === "done" || state === "running" || state === "failed") && "font-medium"
          )}
        >
          {label}
          <span className="sr-only"> ({STEP_STATE_TEXT[state]})</span>
        </p>
        {children}
      </div>
    </li>
  )
}

export function OutdatedNotice({ className }: { className?: string }) {
  return (
    <p
      className={cn(
        "flex items-start gap-2 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:bg-amber-900/20 dark:text-amber-300",
        className
      )}
    >
      <CircleAlert className="mt-px size-3.5 shrink-0" aria-hidden="true" />
      <span>Het aantal aanvragen is gewijzigd nadat de tekst is geschreven. Klik op Opnieuw genereren.</span>
    </p>
  )
}

export function StatusCard({
  report,
  failing,
  busy,
  onRetry,
}: {
  /** null = wordt nog geladen. */
  report: MonthlyReport | null
  failing: boolean
  /** Er is net op een knop gedrukt en de aanvraag loopt. */
  busy: boolean
  onRetry: () => void
}) {
  const status = report?.status ?? "draft"
  const active = isReportActive(status)
  const conceptState: StepState =
    status === "completed" ? "done" : active ? "running" : status === "failed" ? "failed" : "todo"
  const conceptReady = status === "completed"
  const text = report?.report ?? null
  const usage = report?.ai_usage
  const completedAt = formatDateTime(report?.completed_at)
  const period = report?.data?.period
  const periodEnd = period && !period.complete ? formatDayMonth(period.end) : null

  return (
    <ResultCard id="maandrapport-status" title="Status">
      <ol className="space-y-3">
        <Step number={1} label="Concept door Claude" state={conceptState}>
          {active && (
            <p role="status" className="text-xs text-muted-foreground">
              {status === "collecting" ? "Cijfers ophalen…" : "Tekst schrijven…"}
            </p>
          )}
          {report?.status === "draft" && <p className="text-xs text-muted-foreground">Nog niet gegenereerd.</p>}
          {status === "failed" && (
            <div className="space-y-2">
              <p className="text-xs break-words text-status-critical">
                Mislukt: {report?.error_message?.trim() || "onbekende fout"}.
              </p>
              <Button size="sm" variant="outline" onClick={onRetry} disabled={busy}>
                {busy ? <Loader2 className="animate-spin" aria-hidden="true" /> : <RotateCcw aria-hidden="true" />}
                Opnieuw proberen
              </Button>
            </div>
          )}
        </Step>
        <Step number={2} label="Review door specialist" state={conceptReady ? "current" : "todo"} />
        <Step number={3} label="Goedgekeurd" state="todo" />
        <Step number={4} label="Verstuurd door accountmanager" state="todo" />
      </ol>

      {(text || failing || periodEnd || report?.text_outdated) && (
        <div className="space-y-2 border-t pt-3 text-xs text-muted-foreground">
          {text && (
            <p>
              Concept v{text.version} · {modelLabel(report?.model)}
              {/* Tijdens een nieuwe run horen verbruik en tijdstip niet meer bij deze versie. */}
              {!active && usage && usage.calls > 0 && ` · ${formatUsd(usage.cost_usd)}`}
              {!active && completedAt && (
                <>
                  <br />
                  Gemaakt op {completedAt}
                </>
              )}
            </p>
          )}
          {periodEnd && (
            <p>Cijfers t/m {periodEnd}; genereer opnieuw na het einde van de maand voor de hele maand.</p>
          )}
          {report?.text_outdated && <OutdatedNotice />}
          <PollingFailedNotice failing={failing} className="text-xs" />
        </div>
      )}
    </ResultCard>
  )
}
