import { Check, Loader2, Lock } from "lucide-react"

import {
  ACTIVE_STATUSES,
  AUTO_STATUS_LABELS,
  CWV_LABELS,
  SEVERITY_LABELS,
  STATUS_LABELS,
  type AutoStatus,
  type CwvRating,
  type IssueSeverity,
  type LaunchScanDetail,
  type ScanStatus,
} from "@/lib/launch-checklist"
import { cn } from "@/lib/utils"

const pill = "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium whitespace-nowrap"

const TONES = {
  green: "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300",
  amber: "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300",
  red: "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300",
  blue: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300",
  muted: "bg-muted text-muted-foreground",
} as const

export type Tone = keyof typeof TONES

export function Pill({ tone = "muted", className, children }: { tone?: Tone; className?: string; children: React.ReactNode }) {
  return <span className={cn(pill, TONES[tone], className)}>{children}</span>
}

export function ScanStatusBadge({ status }: { status: ScanStatus }) {
  const tone: Tone =
    status === "completed" ? "green" : status === "failed" ? "red" : status === "canceled" ? "muted" : "blue"
  return <Pill tone={tone}>{STATUS_LABELS[status]}</Pill>
}

export function SeverityBadge({ severity }: { severity: IssueSeverity }) {
  const tone: Tone = severity === "hoog" ? "red" : severity === "middel" ? "amber" : "muted"
  return <Pill tone={tone}>{SEVERITY_LABELS[severity]}</Pill>
}

export function CwvBadge({ rating }: { rating: CwvRating | null | undefined }) {
  if (!rating) return <span className="text-xs text-muted-foreground">—</span>
  const tone: Tone = rating === "good" ? "green" : rating === "needs_improvement" ? "amber" : "red"
  return <Pill tone={tone}>{CWV_LABELS[rating]}</Pill>
}

export function HttpStatusBadge({ status, error }: { status: number | null; error?: string | null }) {
  if (status === null) return <Pill tone="red">{error ? "Fout" : "—"}</Pill>
  const tone: Tone = status < 300 ? "green" : status < 400 ? "blue" : "red"
  return <Pill tone={tone}>{status}</Pill>
}

export function StatTile({
  label,
  value,
  hint,
  tone,
}: {
  label: string
  value: React.ReactNode
  hint?: string
  tone?: "good" | "warn" | "bad"
}) {
  return (
    <div className="rounded-lg border bg-card p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p
        className={cn(
          "mt-1 text-2xl font-bold tracking-wide",
          tone === "good" && "text-green-700 dark:text-green-400",
          tone === "warn" && "text-amber-700 dark:text-amber-400",
          tone === "bad" && "text-red-700 dark:text-red-400",
          !tone && "text-primary"
        )}
      >
        {value}
      </p>
      {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
    </div>
  )
}

export const PHASES = [
  { number: 1, title: "Nulmeting & AI scan", available: true },
  { number: 2, title: "GEO/SEO-checklist", available: true },
  { number: 3, title: "Content & onpage", available: true },
  { number: 4, title: "Fase 4", available: false },
]

export function PhaseStepper({
  active,
  completed,
  locked = {},
  onSelect,
}: {
  active: number
  completed: Record<number, boolean>
  locked?: Record<number, string | undefined>
  onSelect?: (phase: number) => void
}) {
  return (
    <ol className="grid gap-2 sm:grid-cols-4">
      {PHASES.map((phase) => {
        const isActive = phase.number === active
        const isDone = completed[phase.number] ?? false
        const lockReason = phase.available ? locked[phase.number] : "Binnenkort"
        const clickable = phase.available && !lockReason && !!onSelect
        return (
          <li key={phase.number}>
            <button
              type="button"
              disabled={!clickable}
              onClick={() => onSelect?.(phase.number)}
              title={lockReason}
              className={cn(
                "flex w-full items-center gap-3 rounded-lg border p-3 text-left transition-colors",
                isActive ? "border-primary/60 bg-primary/5" : clickable ? "hover:bg-muted/50" : "opacity-60",
                !clickable && "cursor-default"
              )}
            >
              <span
                className={cn(
                  "flex size-8 shrink-0 items-center justify-center rounded-full text-sm font-bold",
                  isDone && "bg-green-600 text-white",
                  !isDone && isActive && "bg-primary text-primary-foreground",
                  !isDone && !isActive && "bg-muted text-muted-foreground"
                )}
              >
                {isDone ? <Check className="size-4" /> : lockReason ? <Lock className="size-3.5" /> : phase.number}
              </span>
              <div className="min-w-0">
                <p className="text-xs text-muted-foreground">Fase {phase.number}</p>
                <p className="truncate text-sm font-medium">{phase.available ? phase.title : "Binnenkort"}</p>
              </div>
            </button>
          </li>
        )
      })}
    </ol>
  )
}

export function AutoStatusBadge({ status }: { status: AutoStatus | null | undefined }) {
  if (!status) return <Pill>Niet gescand</Pill>
  const tone: Tone =
    status === "ok" ? "green" : status === "warning" ? "amber" : status === "error" ? "red" : status === "info" ? "blue" : "muted"
  return <Pill tone={tone}>{AUTO_STATUS_LABELS[status]}</Pill>
}

export function PercentRing({ percent, size = 56 }: { percent: number; size?: number }) {
  const stroke = 6
  const r = (size - stroke) / 2
  const c = 2 * Math.PI * r
  const tone = percent >= 80 ? "text-green-600" : percent >= 50 ? "text-amber-500" : "text-red-500"
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="shrink-0" role="img" aria-label={`${percent}% afgerond`}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" strokeWidth={stroke} className="stroke-muted" />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        strokeWidth={stroke}
        strokeLinecap="round"
        strokeDasharray={c}
        strokeDashoffset={c * (1 - percent / 100)}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
        className={cn("stroke-current transition-all", tone)}
      />
      <text x="50%" y="50%" dominantBaseline="central" textAnchor="middle" className="fill-foreground text-xs font-bold">
        {percent}%
      </text>
    </svg>
  )
}

export function ProgressBar({ value, max }: { value: number; max: number }) {
  const pct = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
      <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${max > 0 ? pct : 15}%` }} />
    </div>
  )
}

export const PHASE1_STEPS: ScanStatus[] = ["discovering", "inventory", "vitals", "analyzing"]
export const GEO_STEPS: ScanStatus[] = ["fetching", "linking", "checking", "analyzing"]
/** Fase 3: de scan zelf (zonder AI); de AI-analyse start de gebruiker daarna per selectie. */
export const CONTENT_STEPS: ScanStatus[] = ["fetching", "linking", "checking"]

export function isActive(status: ScanStatus) {
  return ACTIVE_STATUSES.includes(status)
}

export function ScanProgress({ scan, steps = PHASE1_STEPS }: { scan: LaunchScanDetail; steps?: ScanStatus[] }) {
  const currentIndex = steps.indexOf(scan.status)
  let value = 0
  let max = 0
  let detail = ""
  if (scan.status === "inventory") {
    value = scan.inventoried_urls
    max = scan.total_urls
    detail = max ? `${value} / ${max} URL's` : `${value} URL's gecrawld`
  } else if (scan.status === "fetching") {
    value = scan.inventoried_urls
    max = scan.total_urls
    detail = `${value} / ${max} pagina's opgehaald`
  } else if (scan.status === "analyzing" && scan.phase === 3) {
    value = scan.vitals_measured
    max = scan.vitals_total
    detail = `${value} / ${max} pagina's geanalyseerd`
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
        {steps.map((step, index) => (
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

