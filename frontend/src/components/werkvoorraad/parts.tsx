// Kleine bouwstenen van de werkvoorraad, gedeeld door het bord en het paneel. Geen hooks, dus
// zonder "use client": `BoardSkeleton` kan zo ook als Suspense-fallback in de servercomponent.

import { Info, TriangleAlert, X } from "lucide-react"

import { Pill } from "@/components/livegang/shared"
import { Skeleton } from "@/components/ui/skeleton"
import { avatarTone, initialOf, KIND_LABELS, STATUS_ORDER, type WorkKind } from "@/lib/work-queue"
import { cn } from "@/lib/utils"

// Volledige klassennamen (Tailwind), in de vorm van `TONES` in livegang/shared.tsx.
const KIND_TONES: Record<WorkKind, string> = {
  ctr: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300",
  techniek: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800/60 dark:text-zinc-300",
  content: "bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300",
  links: "bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-300",
  update: "bg-indigo-100 text-indigo-800 dark:bg-indigo-900/30 dark:text-indigo-300",
  rapport: "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300",
}

/** Soort van een kaart als gekleurde pil (CTR blauw, Techniek grijs, Content paars, …). */
export function KindBadge({ kind }: { kind: WorkKind }) {
  return <Pill className={KIND_TONES[kind]}>{KIND_LABELS[kind] ?? kind}</Pill>
}

/** Initiaal-rondje van de medewerker; zonder medewerker een gestippeld leeg rondje. */
export function AssigneeAvatar({
  userId,
  name,
  className,
}: {
  userId: string | null
  name: string | null
  className?: string
}) {
  const label = userId ? name?.trim() || "Onbekende medewerker" : "Niet toegewezen"
  if (!userId) {
    return (
      <span
        role="img"
        aria-label={label}
        title={label}
        className={cn("inline-block size-6 shrink-0 rounded-full border border-dashed border-muted-foreground/50", className)}
      />
    )
  }
  return (
    <span
      role="img"
      aria-label={label}
      title={label}
      className={cn(
        "inline-flex size-6 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold select-none",
        avatarTone(userId),
        className
      )}
    >
      {initialOf(name)}
    </span>
  )
}

/** Melding op het bord (bijv. "14 bevindingen afgerond" met "Ongedaan maken", of een fout). */
export function BoardNotice({
  tone,
  message,
  actionLabel,
  onAction,
  onDismiss,
}: {
  tone: "info" | "error"
  message: string
  actionLabel?: string
  onAction?: () => void
  onDismiss?: () => void
}) {
  const Icon = tone === "error" ? TriangleAlert : Info
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={cn(
        "flex items-start gap-2 rounded-lg border bg-card px-3 py-2 text-sm shadow-md",
        tone === "error" ? "border-red-300 text-red-700 dark:border-red-900 dark:text-red-300" : "text-foreground"
      )}
    >
      <Icon className={cn("mt-0.5 size-4 shrink-0", tone === "info" && "text-muted-foreground")} aria-hidden />
      <span className="min-w-0 flex-1 break-words">{message}</span>
      {actionLabel && onAction && (
        <button
          type="button"
          onClick={onAction}
          className="shrink-0 rounded-sm font-medium underline underline-offset-4 outline-none hover:no-underline focus-visible:ring-[3px] focus-visible:ring-ring/50"
        >
          {actionLabel}
        </button>
      )}
      {onDismiss && (
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Melding sluiten"
          className="-mr-1 shrink-0 rounded-sm p-0.5 text-muted-foreground outline-none hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50"
        >
          <X className="size-4" aria-hidden />
        </button>
      )}
    </div>
  )
}

const SKELETON_CARDS = [3, 2, 2, 1]

/** Eerste lading van het bord: kop en vier kolommen met grijze kaarten. */
export function BoardSkeleton() {
  return (
    <div aria-busy="true" aria-label="Werkvoorraad laden" className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-2">
          <Skeleton className="h-3 w-16" />
          <Skeleton className="h-8 w-48" />
          <Skeleton className="h-4 w-96 max-w-full" />
        </div>
        <div className="flex flex-wrap gap-2">
          <Skeleton className="h-9 w-32 rounded-full" />
          <Skeleton className="h-9 w-36 rounded-full" />
          <Skeleton className="h-9 w-24 rounded-full" />
        </div>
      </div>
      <div className="flex gap-3 overflow-hidden">
        {STATUS_ORDER.map((status, column) => (
          <div key={status} className="w-[268px] shrink-0 space-y-2 rounded-xl bg-muted/60 p-2">
            <div className="flex items-center justify-between px-1 py-1">
              <Skeleton className="h-4 w-20" />
              <Skeleton className="h-5 w-7 rounded-full" />
            </div>
            {Array.from({ length: SKELETON_CARDS[column] }, (_, index) => (
              <Skeleton key={index} className="h-[104px] w-full rounded-lg bg-card" />
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}
