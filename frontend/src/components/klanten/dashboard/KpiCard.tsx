import Link from "next/link"

import { cn } from "@/lib/utils"

export type KpiTone = "good" | "bad" | "accent" | "warn" | "muted"

const TONE_CLASSES: Record<KpiTone, string> = {
  good: "text-green-700 dark:text-green-400",
  bad: "text-red-700 dark:text-red-400",
  accent: "text-primary",
  warn: "text-orange-600 dark:text-orange-400",
  muted: "text-muted-foreground",
}

const cardClass = "flex flex-col gap-1.5 rounded-xl border bg-card px-5 py-[18px]"

export function KpiCard({
  label,
  value,
  hint,
  tone = "muted",
  href,
}: {
  label: string
  value: string
  /** Regel onder de waarde; weg bij `null`. */
  hint?: React.ReactNode
  tone?: KpiTone
  /** Maakt de hele kaart klikbaar. */
  href?: string
}) {
  const content = (
    <>
      <p className="text-[13px] font-medium text-muted-foreground">{label}</p>
      <p className="text-[28px] leading-tight font-bold tabular-nums text-foreground">
        {value}
      </p>
      {hint != null && (
        <p className={cn("text-xs font-medium", TONE_CLASSES[tone])}>{hint}</p>
      )}
    </>
  )

  if (href) {
    return (
      <Link
        href={href}
        className={cn(
          cardClass,
          "transition hover:border-neutral-400 hover:shadow-sm focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none dark:hover:border-white/30"
        )}
      >
        {content}
      </Link>
    )
  }

  return <div className={cardClass}>{content}</div>
}
