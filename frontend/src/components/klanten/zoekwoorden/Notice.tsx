import { AlertTriangle, CircleAlert, Info } from "lucide-react"

import { cn } from "@/lib/utils"

export type NoticeTone = "neutral" | "amber" | "red"

const NOTICE_CLASSES: Record<NoticeTone, string> = {
  neutral: "border-border bg-card text-foreground",
  amber: "border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-500/50 dark:bg-amber-900/20 dark:text-amber-200",
  red: "border-red-300 bg-card text-red-700 dark:border-red-500/60 dark:text-red-300",
}

const NOTICE_ICONS = { neutral: Info, amber: AlertTriangle, red: CircleAlert } as const

/**
 * Meldingsbalk in de bestaande opmaak (neutraal, amber of rood), met optioneel een knop.
 * Gedeeld door de schermen onder Zoekwoorden (Concurrenten en Content gap).
 */
export function Notice({
  tone,
  children,
  action,
  icon,
}: {
  tone: NoticeTone
  children: React.ReactNode
  action?: React.ReactNode
  icon?: React.ReactNode
}) {
  const Icon = NOTICE_ICONS[tone]
  return (
    <div
      role={tone === "red" ? "alert" : "status"}
      className={cn("flex flex-wrap items-center gap-3 rounded-md border px-3 py-2 text-sm", NOTICE_CLASSES[tone])}
    >
      {icon ?? <Icon className="size-4 shrink-0" aria-hidden="true" />}
      <span className="min-w-0 flex-1">{children}</span>
      {action}
    </div>
  )
}
