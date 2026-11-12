import { Check, Loader2, Lock, RefreshCw } from "lucide-react"

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

/** Compacte cijfergroep: één rand eromheen en lijnen tussen de cellen (gap-px op bg-border). */
export function StatGrid({ className, children }: { className?: string; children: React.ReactNode }) {
  return <div className={cn("grid gap-px overflow-hidden rounded-lg border bg-border", className)}>{children}</div>
}

export function CompactStat({
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
    <div className="min-w-0 bg-card px-3 py-2">
      <p className="truncate text-xs text-muted-foreground" title={label}>
        {label}
      </p>
      <p
        className={cn(
          "text-xl font-bold tracking-wide",
          tone === "good" && "text-green-700 dark:text-green-400",
          tone === "warn" && "text-amber-700 dark:text-amber-400",
          tone === "bad" && "text-red-700 dark:text-red-400",
          !tone && "text-primary"
        )}
      >
        {value}
      </p>
      {hint && (
        <p className="truncate text-[11px] text-muted-foreground" title={hint}>
          {hint}
        </p>
      )}
    </div>
  )
}

export const PHASES = [
  { number: 1, title: "Nulmeting & AI scan", description: "Inventaris, Core Web Vitals en AI-vindbaarheid", available: true },
  { number: 2, title: "GEO/SEO-checklist", description: "Schema, entiteit-signalen en AI-toegang", available: true },
  { number: 3, title: "Content & onpage", description: "Meta, koppen en herschrijfvoorstellen", available: true },
  { number: 4, title: "Kwartaal GEO", description: "Herhaalscan, vergelijking en rapportage per kwartaal", available: true },
]

export function PhaseStepper({
  active,
  completed,
  outdated = {},
  locked = {},
  onSelect,
}: {
  active: number
  completed: Record<number, boolean>
  /** Afgeronde fases die op een oudere nulmeting zijn gebaseerd (oranje i.p.v. groen). */
  outdated?: Record<number, boolean>
  locked?: Record<number, string | undefined>
  onSelect?: (phase: number) => void
}) {
  return (
    <nav aria-label="Fases">
      <ol className="grid gap-1 p-2 sm:grid-cols-4">
        {PHASES.map((phase, index) => {
          const isActive = phase.number === active
          const isDone = completed[phase.number] ?? false
          const isOutdated = isDone && (outdated[phase.number] ?? false)
          const lockReason = phase.available ? locked[phase.number] : undefined
          const clickable = phase.available && !lockReason && !!onSelect
          const isLast = index === PHASES.length - 1
          const outdatedHint = isOutdated ? "Gebaseerd op een oudere nulmeting — scan opnieuw." : undefined
          const status: { label: string; tone: Tone } = !phase.available
            ? { label: "Binnenkort", tone: "muted" }
            : isOutdated
              ? { label: "Verouderd", tone: "amber" }
              : isDone
                ? { label: "Afgerond", tone: "green" }
                : lockReason
                  ? { label: "Vergrendeld", tone: "muted" }
                  : isActive
                    ? { label: "Bezig", tone: "blue" }
                    : { label: "Open", tone: "muted" }
          return (
            <li key={phase.number} className="min-w-0">
              <button
                type="button"
                disabled={!clickable}
                onClick={() => onSelect?.(phase.number)}
                title={lockReason ?? outdatedHint}
                aria-current={isActive ? "step" : undefined}
                className={cn(
                  "relative flex h-full w-full gap-3 rounded-md p-3 text-left transition-colors sm:flex-col sm:gap-3",
                  isActive ? "bg-primary/5" : clickable ? "hover:bg-muted/60" : "cursor-default",
                  !phase.available || lockReason ? "opacity-60" : undefined
                )}
              >
                <span className="flex items-center sm:w-full">
                  <span
                    className={cn(
                      "flex size-9 shrink-0 items-center justify-center rounded-full text-sm font-bold ring-4 ring-card",
                      isOutdated && "bg-amber-500 text-white",
                      isDone && !isOutdated && "bg-green-600 text-white",
                      !isDone && isActive && "bg-primary text-primary-foreground",
                      !isDone && !isActive && "border bg-muted text-muted-foreground"
                    )}
                  >
                    {isOutdated ? (
                      <RefreshCw className="size-4" />
                    ) : isDone ? (
                      <Check className="size-4" />
                    ) : lockReason || !phase.available ? (
                      <Lock className="size-3.5" />
                    ) : (
                      phase.number
                    )}
                  </span>
                  {!isLast && (
                    <span
                      aria-hidden
                      className={cn(
                        "ml-3 hidden h-0.5 flex-1 rounded-full sm:block",
                        isOutdated ? "bg-amber-500/70" : isDone ? "bg-green-600/70" : "bg-border"
                      )}
                    />
                  )}
                </span>
                <span className="min-w-0 flex-1 space-y-1">
                  <span className="flex items-center gap-2">
                    <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Fase {phase.number}</span>
                    <Pill tone={status.tone}>{status.label}</Pill>
                  </span>
                  <span className={cn("block text-sm leading-snug", isActive ? "font-semibold" : "font-medium")}>{phase.title}</span>
                  <span className="block text-xs leading-snug text-muted-foreground">{lockReason ?? outdatedHint ?? phase.description}</span>
                </span>
                {isActive && <span aria-hidden className="absolute inset-x-3 bottom-0 h-0.5 rounded-full bg-primary" />}
              </button>
            </li>
          )
        })}
      </ol>
    </nav>
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
/** Fase 4: herhaalscan, opnieuw ophalen voor schema, vergelijken en conceptrapport. */
export const QUARTERLY_STEPS: ScanStatus[] = ["discovering", "inventory", "fetching", "checking", "analyzing"]

export function isActive(status: ScanStatus) {
  return ACTIVE_STATUSES.includes(status)
}

export function ScanProgress({
  scan,
  steps = PHASE1_STEPS,
  bare = false,
}: {
  scan: LaunchScanDetail
  steps?: ScanStatus[]
  /** Zonder eigen kaartrand, voor gebruik binnen een PanelRow. */
  bare?: boolean
}) {
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
    <div className={cn("space-y-3", !bare && "rounded-lg border bg-card p-4")}>
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

/** Blok per fase (geen kaart): kop met titel/omschrijving, daaronder rijen (PanelRow) en eventueel tabs (PanelTabs). */
export function PhasePanel({
  title,
  description,
  aside,
  children,
}: {
  title: React.ReactNode
  description: React.ReactNode
  aside?: React.ReactNode
  children?: React.ReactNode
}) {
  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-start gap-4">
        <div className="min-w-0 flex-1 space-y-1">
          <h2 className="text-lg font-bold tracking-wide text-primary">{title}</h2>
          <p className="text-sm text-muted-foreground">{description}</p>
        </div>
        {aside}
      </div>
      {children}
    </section>
  )
}

const ROW_TONES = {
  default: "",
  muted: "rounded-lg bg-muted/50 px-4 py-3",
  warning: "rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-amber-900 dark:bg-amber-900/20 dark:text-amber-200",
  error: "rounded-md border border-red-300 px-3 py-2 text-red-700 dark:text-red-300",
} as const

export function PanelRow({
  tone = "default",
  className,
  children,
}: {
  tone?: keyof typeof ROW_TONES
  className?: string
  children: React.ReactNode
}) {
  return <div className={cn("text-sm", ROW_TONES[tone], className)}>{children}</div>
}

export function PanelTabs<K extends string>({
  tabs,
  active,
  onSelect,
}: {
  tabs: { key: K; label: React.ReactNode; disabled?: boolean }[]
  active: K
  onSelect: (key: K) => void
}) {
  return (
    <div role="tablist" className="flex gap-1 overflow-x-auto border-b">
      {tabs.map((t) => (
        <button
          key={t.key}
          type="button"
          role="tab"
          aria-selected={active === t.key}
          disabled={t.disabled}
          onClick={() => onSelect(t.key)}
          className={cn(
            "-mb-px whitespace-nowrap border-b-2 px-4 py-2 text-sm transition-colors",
            active === t.key
              ? "border-primary font-medium text-foreground"
              : "border-transparent text-muted-foreground hover:text-foreground",
            t.disabled && "cursor-not-allowed opacity-50 hover:text-muted-foreground"
          )}
        >
          {t.label}
        </button>
      ))}
    </div>
  )
}
