import { Check, Lock } from "lucide-react"

import {
  CWV_LABELS,
  SEVERITY_LABELS,
  STATUS_LABELS,
  type CwvRating,
  type IssueSeverity,
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
  { number: 2, title: "Fase 2", available: false },
  { number: 3, title: "Fase 3", available: false },
  { number: 4, title: "Fase 4", available: false },
]

export function PhaseStepper({ completed }: { completed: boolean }) {
  return (
    <ol className="grid gap-2 sm:grid-cols-4">
      {PHASES.map((phase) => {
        const active = phase.number === 1
        return (
          <li
            key={phase.number}
            className={cn(
              "flex items-center gap-3 rounded-lg border p-3",
              active ? "border-primary/60 bg-primary/5" : "opacity-60"
            )}
          >
            <span
              className={cn(
                "flex size-8 shrink-0 items-center justify-center rounded-full text-sm font-bold",
                active && completed && "bg-green-600 text-white",
                active && !completed && "bg-primary text-primary-foreground",
                !active && "bg-muted text-muted-foreground"
              )}
            >
              {active && completed ? <Check className="size-4" /> : phase.available ? phase.number : <Lock className="size-3.5" />}
            </span>
            <div className="min-w-0">
              <p className="text-xs text-muted-foreground">Fase {phase.number}</p>
              <p className="truncate text-sm font-medium">{phase.available ? phase.title : "Binnenkort"}</p>
            </div>
          </li>
        )
      })}
    </ol>
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
