"use client"

import { ArrowRight, Check, CircleAlert, Loader2, MessageSquare, Pencil, RotateCcw, Sparkles } from "lucide-react"

import { MetricTiles } from "@/components/klanten/maandrapport/MetricTiles"
import { OutdatedNotice } from "@/components/klanten/maandrapport/SideCards"
import { Pill } from "@/components/livegang/shared"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import {
  isReportActive,
  monthLabel,
  monthName,
  shiftMonth,
  type MonthlyReport,
  type ReportItem,
  type ReportText,
} from "@/lib/monthly-report"
import { cn } from "@/lib/utils"

function ItemList({
  title,
  items,
  empty,
  icon,
}: {
  title: string
  items: ReportItem[]
  empty: string
  icon: "check" | "arrow"
}) {
  return (
    <div className="space-y-2">
      <h4 className="text-base font-semibold">{title}</h4>
      {items.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">{empty}</p>
      ) : (
        <ul className="space-y-1.5">
          {items.map((item, index) => (
            <li key={index} className="flex items-start gap-2 text-[13px] leading-5">
              {icon === "check" ? (
                <Check className="mt-0.5 size-4 shrink-0 text-status-good" aria-hidden="true" />
              ) : (
                <ArrowRight className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden="true" />
              )}
              <span className="min-w-0 break-words">{item.text}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function ReviewNotes({ notes }: { notes: ReportText["review_notes"] }) {
  if (notes.length === 0) return null
  return (
    <div className="rounded-lg bg-amber-50 px-4 py-3 dark:bg-amber-900/20">
      <p className="sr-only">Opmerkingen voor de specialist (komen niet in het rapport)</p>
      <ul className="space-y-1.5">
        {notes.map((note, index) => (
          <li key={index} className="flex items-start gap-1.5 text-xs text-amber-800 dark:text-amber-300">
            <MessageSquare className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
            <span className="min-w-0 break-words">
              Review: {note.text}
              {note.source === "check" && (
                <Pill
                  tone="amber"
                  className="ml-1.5 border border-amber-300 px-1.5 py-0 align-[1px] text-[10px] dark:border-amber-700"
                >
                  controle
                </Pill>
              )}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function SummarySkeleton() {
  return (
    <div className="space-y-2" aria-hidden="true">
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-4 w-11/12" />
      <Skeleton className="h-4 w-4/5" />
      <Skeleton className="mt-4 h-4 w-full" />
      <Skeleton className="h-4 w-3/4" />
    </div>
  )
}

function ListSkeleton() {
  return (
    <div className="space-y-2" aria-hidden="true">
      <Skeleton className="h-5 w-32" />
      <Skeleton className="h-4 w-5/6" />
      <Skeleton className="h-4 w-2/3" />
      <Skeleton className="h-4 w-3/4" />
    </div>
  )
}

function SheetMessage({ children, action }: { children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-start gap-3 rounded-lg border border-dashed px-4 py-5 text-[13px] text-muted-foreground">
      {children}
      {action}
    </div>
  )
}

/**
 * Het "Voorbeeld": het rapportvel zoals de klant het krijgt (Figma 13, rechterkolom).
 *
 * - Zonder rapport (draft): uitleg met "Genereren"; de tegel Aanvragen werkt al.
 * - Eerste run: een skelet in plaats van de tekst.
 * - Nieuwe run: het vorige vel blijft gedimd staan tot de nieuwe versie er is.
 * - Mislukt zonder eerder rapport: de foutmelding met "Opnieuw proberen".
 */
export function ReportPreview({
  customerId,
  customerName,
  month,
  report,
  busy,
  onGenerate,
  onLeadsSaved,
}: {
  customerId: string
  customerName: string
  month: string
  report: MonthlyReport
  /** Er is net op Genereren gedrukt en de aanvraag loopt. */
  busy: boolean
  onGenerate: () => void
  onLeadsSaved: (report: MonthlyReport) => void
}) {
  const active = isReportActive(report.status)
  const text = report.report
  const stale = active && text !== null
  const label = monthLabel(month)

  let body: React.ReactNode
  if (text) {
    body = (
      <div className="space-y-2.5 text-sm leading-[22px]">
        {text.summary.map((paragraph, index) => (
          <p key={index}>{paragraph}</p>
        ))}
      </div>
    )
  } else if (active) {
    body = (
      <>
        <p role="status" className="flex items-center gap-2 text-[13px] text-muted-foreground">
          <Loader2 className="size-4 animate-spin" aria-hidden="true" />
          {report.status === "collecting" ? "Cijfers ophalen…" : "Tekst schrijven…"}
        </p>
        <SummarySkeleton />
      </>
    )
  } else if (report.status === "failed") {
    body = (
      <SheetMessage
        action={
          <Button size="sm" variant="outline" onClick={onGenerate} disabled={busy}>
            {busy ? <Loader2 className="animate-spin" aria-hidden="true" /> : <RotateCcw aria-hidden="true" />}
            Opnieuw proberen
          </Button>
        }
      >
        <p className="flex items-start gap-2 text-status-critical">
          <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          <span className="break-words">
            Het rapport kon niet worden opgesteld: {report.error_message?.trim() || "onbekende fout"}.
          </span>
        </p>
      </SheetMessage>
    )
  } else {
    body = (
      <SheetMessage
        action={
          <Button size="sm" onClick={onGenerate} disabled={busy}>
            {busy ? <Loader2 className="animate-spin" aria-hidden="true" /> : <Sparkles aria-hidden="true" />}
            Genereren
          </Button>
        }
      >
        <p className="font-medium text-foreground">Nog geen rapport voor {label}</p>
        <p>
          Claude haalt de cijfers op uit Search Console en ProRankTracker, zet het uitgevoerde werk op een rij en schrijft
          daar een rapport van in begrijpelijke taal. Daarna kijkt de specialist het na; er wordt niets verstuurd. Het
          aantal aanvragen kun je nu al invullen in de tegel hieronder.
        </p>
      </SheetMessage>
    )
  }

  return (
    <section aria-labelledby="maandrapport-voorbeeld" className="min-w-0 space-y-3 rounded-xl bg-muted p-4 sm:p-6">
      <div className="flex items-center justify-between gap-3">
        <h2 id="maandrapport-voorbeeld" className="text-xs text-muted-foreground">
          Voorbeeld · pagina 1
        </h2>
        {/* Een uitgeschakelde knop krijgt geen muisgebeurtenissen; de uitleg staat op de omhulling. */}
        <span title="Binnenkort">
          <Button variant="ghost" size="sm" disabled className="text-muted-foreground">
            <Pencil aria-hidden="true" />
            Tekst bewerken
          </Button>
        </span>
      </div>

      {stale && (
        <p role="status" className="flex items-center gap-2 text-[13px] text-muted-foreground">
          <Loader2 className="size-4 shrink-0 animate-spin" aria-hidden="true" />
          Er wordt een nieuwe versie geschreven…
        </p>
      )}

      <article
        aria-label={`Maandrapport ${label}`}
        className={cn(
          "@container space-y-4 rounded-md bg-card px-5 py-6 shadow-xs transition-opacity sm:px-10 sm:py-10",
          stale && "opacity-60"
        )}
      >
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 pb-2">
          <p className="font-bold text-primary">{customerName}</p>
          <p className="text-xs text-muted-foreground">SEO-rapport · {label}</p>
        </div>

        <h3 className="text-[22px] leading-tight font-bold">Samenvatting</h3>
        {body}

        <MetricTiles
          customerId={customerId}
          month={month}
          metrics={report.data?.metrics ?? null}
          leads={report.leads}
          previousMonthName={monthName(shiftMonth(month, -1))}
          onLeadsSaved={onLeadsSaved}
        />
        {report.text_outdated && <OutdatedNotice />}

        {text ? (
          <>
            <ItemList
              title="Wat we deden"
              items={text.work_done}
              empty="Geen geregistreerd werk in deze maand."
              icon="check"
            />
            <ItemList
              title="Volgende maand"
              items={text.next_month}
              empty="Nog geen openstaand werk geregistreerd."
              icon="arrow"
            />
            <ReviewNotes notes={text.review_notes} />
          </>
        ) : (
          active && (
            <>
              <ListSkeleton />
              <ListSkeleton />
            </>
          )
        )}
      </article>
    </section>
  )
}
