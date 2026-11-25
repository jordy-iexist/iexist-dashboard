"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { ArrowRight, ChevronDown, Loader2, Play, Puzzle, RefreshCw, RotateCcw, SearchX, Users } from "lucide-react"

import { ResultCard, formatInt, formatShortDate } from "@/components/klanten/analyses/result-parts"
import { ContentGapSkeleton } from "@/components/klanten/zoekwoorden/content-gap/ContentGapSkeleton"
import { GapKpis } from "@/components/klanten/zoekwoorden/content-gap/GapKpis"
import { GapTable } from "@/components/klanten/zoekwoorden/content-gap/GapTable"
import { Notice } from "@/components/klanten/zoekwoorden/Notice"
import { Pill, PollingFailedNotice } from "@/components/livegang/shared"
import { Button } from "@/components/ui/button"
import { usePolling } from "@/hooks/use-polling"
import { customerHref } from "@/lib/active-customer"
import { TOP_COMPETITORS } from "@/lib/keyword-competitors"
import {
  ContentGapError,
  MIN_GAP_COMPETITORS,
  fetchContentGap,
  isContentGapActive,
  startContentGap,
  type ContentGapBlocked,
  type ContentGapOverview,
  type ContentGapStatus,
} from "@/lib/keyword-content-gap"

export type ContentGapViewProps = {
  customerId: string
  customerName: string
  domain: string
}

const POLL_INTERVAL_MS = 3000

/** Wat er gebeurt tijdens een lopende run. */
const STATUS_LINES: Partial<Record<ContentGapStatus, string>> = {
  pending: "In de wachtrij…",
  collecting: "Zoekwoordlijsten van de concurrenten vergelijken en posities ophalen…",
  enriching: "Volume, KD en intentie ophalen uit Ahrefs…",
}

function errorMessage(err: unknown) {
  return err instanceof Error && err.message ? err.message : "Er ging iets mis."
}

/** Uitleg per reden waarom starten niet kan; `link` = verwijzen naar het Concurrenten-scherm. */
const BLOCKED_TEXTS: Record<ContentGapBlocked, { title: string; text: string; link: boolean }> = {
  no_scan: {
    title: "Eerst een concurrentenscan nodig",
    text: "De content gap vergelijkt de zoekwoorden van de top 5-concurrenten met die van de klant. Haal daarom eerst de concurrenten op onder Zoekwoorden › Concurrenten.",
    link: true,
  },
  too_few_competitors: {
    title: "Te weinig concurrenten in de top 5",
    text: `Voor een content gap moeten er minstens ${MIN_GAP_COMPETITORS} concurrenten in de top 5 staan. Voeg op het Concurrenten-scherm een concurrent toe of tel een uitgesloten concurrent weer mee, en werk het overzicht bij.`,
    link: true,
  },
  ahrefs_not_configured: {
    title: "Ahrefs is niet ingesteld",
    text: "De content gap haalt zijn zoekwoorden en cijfers uit Ahrefs. Stel eerst een Ahrefs-sleutel in.",
    link: false,
  },
}

function ConcurrentenLink({ customerId, size }: { customerId: string; size?: "sm" }) {
  return (
    <Button asChild variant="outline" size={size}>
      <Link href={customerHref("zoekwoordConcurrenten", customerId)}>
        <Users aria-hidden="true" />
        Naar Concurrenten
      </Link>
    </Button>
  )
}

/** Geblokkeerd zonder resultaat: uitleg en (waar het helpt) de weg naar het Concurrenten-scherm. */
function BlockedCard({ reason, customerId }: { reason: ContentGapBlocked; customerId: string }) {
  const { title, text, link } = BLOCKED_TEXTS[reason]
  return (
    <section
      aria-labelledby="content-gap-geblokkeerd"
      className="flex flex-col items-center gap-3 rounded-xl border border-dashed bg-card px-6 py-10 text-center"
    >
      <span className="flex size-10 items-center justify-center rounded-full bg-muted">
        <Puzzle className="size-5 text-muted-foreground" aria-hidden="true" />
      </span>
      <h2 id="content-gap-geblokkeerd" className="text-base font-semibold">
        {title}
      </h2>
      <p className="max-w-xl text-[13px] text-muted-foreground">{text}</p>
      {link && (
        <div className="mt-1">
          <ConcurrentenLink customerId={customerId} />
        </div>
      )}
    </section>
  )
}

/** Nog geen resultaat: uitleg en de knop om de eerste run te starten. */
function StartCard({
  overview,
  customerName,
  busy,
  onStart,
}: {
  overview: ContentGapOverview
  customerName: string
  busy: boolean
  onStart: () => void
}) {
  const competitors = overview.competitors.length || TOP_COMPETITORS
  return (
    <section
      aria-labelledby="content-gap-starten"
      className="flex flex-col items-center gap-3 rounded-xl border border-dashed bg-card px-6 py-10 text-center"
    >
      <span className="flex size-10 items-center justify-center rounded-full bg-muted">
        <Puzzle className="size-5 text-muted-foreground" aria-hidden="true" />
      </span>
      <h2 id="content-gap-starten" className="text-base font-semibold">
        Nog geen content gap opgehaald
      </h2>
      <p className="max-w-xl text-[13px] text-muted-foreground">
        Zoek de zoekwoorden waarop minstens {MIN_GAP_COMPETITORS} van de {competitors} concurrenten uit de
        concurrentenscan in de top 10 van Google staan en {customerName} niet. Per zoekwoord zie je het volume, de
        moeilijkheid, de intentie en de posities van de concurrenten.
      </p>
      <Button onClick={onStart} disabled={busy} className="mt-1 font-semibold">
        {busy ? <Loader2 className="animate-spin" aria-hidden="true" /> : <Play aria-hidden="true" />}
        {overview.status === "failed" ? "Opnieuw starten" : "Content gap starten"}
      </Button>
      <p className="text-xs text-muted-foreground">Kost maximaal {formatInt(overview.max_units)} Ahrefs-units.</p>
    </section>
  )
}

/** Resultaat zonder gap-zoekwoorden. */
function EmptyResult({ customerName }: { customerName: string }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed px-4 py-8 text-center">
      <SearchX className="size-5 text-muted-foreground" aria-hidden="true" />
      <p className="text-sm font-medium">Geen gap-zoekwoorden gevonden</p>
      <p className="max-w-xl text-[13px] text-muted-foreground">
        Er is geen zoekwoord waarop minstens {MIN_GAP_COMPETITORS} concurrenten in de top 10 staan en {customerName}{" "}
        niet. Vernieuw de concurrentenscan als de concurrenten veranderd zijn.
      </p>
    </div>
  )
}

/** Kaart die in een volgende stap gevuld wordt: alleen de titel, "Binnenkort" en één zin. */
function SoonCard({ id, title, description, text }: { id: string; title: string; description: string; text: string }) {
  return (
    <ResultCard id={id} title={title} description={description} aside={<Pill>Binnenkort</Pill>}>
      <p className="rounded-lg border border-dashed px-4 py-5 text-[13px] text-muted-foreground">{text}</p>
    </ResultCard>
  )
}

/**
 * Zoekwoorden › Content gap van één klant (Figma 46 · Zoekwoorden – Content gap).
 *
 * - Bij het openen wordt de stand opgehaald; zonder gegevens is de status `idle`.
 * - Starten gebeurt alleen hier (de knop op het Concurrenten-scherm opent dit scherm).
 * - Zolang er een run loopt wordt het elke 3 seconden ververst; een eerder resultaat blijft
 *   dan zichtbaar met een balk "Wordt bijgewerkt…".
 * - Mislukt een run, dan blijft het vorige resultaat staan met een rode melding.
 */
export function ContentGapView({ customerId, customerName, domain }: ContentGapViewProps) {
  const [overview, setOverview] = useState<ContentGapOverview | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [actionInfo, setActionInfo] = useState<string | null>(null)

  useEffect(() => {
    let ignore = false
    fetchContentGap(customerId)
      .then((next) => {
        if (ignore) return
        setOverview(next)
        setLoadError(null)
      })
      .catch((err: unknown) => {
        if (!ignore) setLoadError(errorMessage(err))
      })
    return () => {
      ignore = true
    }
  }, [customerId, attempt])

  const active = overview !== null && isContentGapActive(overview.status)

  // Is de lopende run klaar, dan is de melding "er loopt al een run" achterhaald.
  const [wasActive, setWasActive] = useState(active)
  if (active !== wasActive) {
    setWasActive(active)
    if (!active) setActionInfo(null)
  }

  const { failing } = usePolling(
    async () => {
      setOverview(await fetchContentGap(customerId))
    },
    active,
    POLL_INTERVAL_MS
  )

  async function reload() {
    const latest = await fetchContentGap(customerId).catch(() => null)
    if (latest) setOverview(latest)
  }

  async function start() {
    setBusy(true)
    setActionError(null)
    setActionInfo(null)
    try {
      setOverview(await startContentGap(customerId))
    } catch (err) {
      // 409 = er loopt al een run: de actuele stand tonen (de polling neemt het over).
      if (err instanceof ContentGapError && err.status === 409) {
        setActionInfo("Er loopt al een run; de voortgang hieronder wordt vanzelf bijgewerkt.")
      } else {
        setActionError(errorMessage(err))
      }
      await reload()
    } finally {
      setBusy(false)
    }
  }

  const hasResult = overview?.has_result ?? false
  const blocked = overview?.blocked ?? null
  const statusLine = overview ? STATUS_LINES[overview.status] : undefined
  const completedAt = formatShortDate(overview?.completed_at)
  const competitorCount = overview?.competitors.length || TOP_COMPETITORS
  const startDisabled = !overview || active || busy || blocked !== null
  const truncated = overview !== null && hasResult && overview.found > overview.keywords.length

  const restartButton = (label: string) => (
    <Button size="sm" onClick={() => void start()} disabled={startDisabled}>
      {busy ? <Loader2 className="animate-spin" aria-hidden="true" /> : <RefreshCw aria-hidden="true" />}
      {label}
    </Button>
  )

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0 max-w-3xl space-y-1">
          <p className="text-[13px] text-muted-foreground">
            Zoekwoorden <span aria-hidden="true">/</span> {customerName}
          </p>
          <h1 className="text-2xl font-bold tracking-tight break-words sm:text-[28px]">Content gap</h1>
          <p className="text-[13px] text-muted-foreground">
            Zoekwoorden waarop minstens {MIN_GAP_COMPETITORS} van de {competitorCount} concurrenten in de top 10 staan en{" "}
            {customerName} niet. Bron: Ahrefs.
          </p>
          <p className="text-xs text-muted-foreground">
            <span className="break-all">{overview?.customer_domain || domain}</span>
            {hasResult && completedAt && (
              <>
                {` · Bijgewerkt op ${completedAt}`}
                {` · ${formatInt(overview?.units)} Ahrefs-units`}
              </>
            )}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {hasResult && (
            <span
              title={
                active
                  ? "Er loopt al een run; wacht tot die klaar is."
                  : overview && !blocked
                    ? `Haalt de content gap opnieuw op uit Ahrefs (maximaal ${formatInt(overview.max_units)} units).`
                    : undefined
              }
            >
              <Button variant="outline" onClick={() => void start()} disabled={startDisabled}>
                {active || busy ? (
                  <Loader2 className="animate-spin" aria-hidden="true" />
                ) : (
                  <RefreshCw aria-hidden="true" />
                )}
                Opnieuw ophalen
              </Button>
            </span>
          )}
          <Pill>Binnenkort</Pill>
          {/* Een uitgeschakelde knop krijgt geen muisgebeurtenissen; de uitleg staat op de omhulling. */}
          <span title="Binnenkort">
            <Button variant="outline" disabled className="font-semibold">
              Filters: ≥ {MIN_GAP_COMPETITORS} concurrenten · NL
              <ChevronDown aria-hidden="true" />
            </Button>
          </span>
          <span title="Binnenkort">
            <Button disabled className="font-semibold">
              Selectie naar Zoekwoordkansen
              <ArrowRight aria-hidden="true" />
            </Button>
          </span>
        </div>
      </header>

      {loadError && !overview ? (
        <Notice
          tone="red"
          action={
            <Button size="sm" variant="outline" onClick={() => setAttempt((value) => value + 1)}>
              <RotateCcw aria-hidden="true" />
              Opnieuw proberen
            </Button>
          }
        >
          De content gap kon niet worden opgehaald: {loadError}
        </Notice>
      ) : !overview ? (
        <ContentGapSkeleton />
      ) : (
        <>
          {(actionError ||
            actionInfo ||
            failing ||
            (hasResult && blocked) ||
            overview.status === "failed" ||
            (hasResult && overview.stale && !active) ||
            overview.warnings.length > 0 ||
            truncated ||
            (active && hasResult)) && (
            <div className="space-y-2">
              {actionError && <Notice tone="red">{actionError}</Notice>}
              {actionInfo && <Notice tone="neutral">{actionInfo}</Notice>}
              <PollingFailedNotice failing={failing} />
              {/* Zonder resultaat staat de uitleg in de kaart hieronder. */}
              {hasResult && blocked && (
                <Notice
                  tone="amber"
                  action={BLOCKED_TEXTS[blocked].link ? <ConcurrentenLink customerId={customerId} size="sm" /> : undefined}
                >
                  <span className="font-medium">{BLOCKED_TEXTS[blocked].title}.</span> {BLOCKED_TEXTS[blocked].text}
                </Notice>
              )}
              {overview.status === "failed" && (
                <Notice
                  tone="red"
                  // Zonder resultaat staat de knop in de startkaart.
                  action={hasResult ? restartButton("Opnieuw starten") : undefined}
                >
                  {hasResult ? "De laatste run is mislukt: " : "Ophalen is mislukt: "}
                  {overview.error || "onbekende fout."}
                  {hasResult && completedAt && (
                    <span className="mt-0.5 block text-xs">De cijfers hieronder zijn van {completedAt}.</span>
                  )}
                </Notice>
              )}
              {hasResult && overview.stale && !active && (
                <Notice tone="amber" action={restartButton("Opnieuw ophalen")}>
                  De concurrentenscan is vernieuwd sinds deze content gap is opgehaald. Haal hem opnieuw op om de
                  nieuwe concurrenten en zoekwoorden mee te nemen.
                </Notice>
              )}
              {overview.warnings.length > 0 && (
                <Notice tone="amber">
                  {overview.warnings.length === 1 ? (
                    overview.warnings[0]
                  ) : (
                    <ul className="list-disc space-y-0.5 pl-4">
                      {overview.warnings.map((warning, index) => (
                        <li key={index}>{warning}</li>
                      ))}
                    </ul>
                  )}
                </Notice>
              )}
              {truncated && (
                <Notice tone="neutral">
                  Er zijn {formatInt(overview.found)} gap-zoekwoorden gevonden. De{" "}
                  {formatInt(overview.keywords.length)} met de meeste concurrenten zijn uitgewerkt; de rest valt buiten
                  het plafond van {formatInt(overview.max_units)} Ahrefs-units per run.
                </Notice>
              )}
              {active && hasResult && (
                <Notice tone="neutral" icon={<Loader2 className="size-4 shrink-0 animate-spin" aria-hidden="true" />}>
                  <span className="font-medium">Wordt bijgewerkt…</span>
                  {statusLine && <span className="text-muted-foreground"> {statusLine}</span>}
                </Notice>
              )}
            </div>
          )}

          {!hasResult && active ? (
            <div className="space-y-3">
              <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="size-4 shrink-0 animate-spin" aria-hidden="true" />
                {statusLine ?? "Bezig…"}
              </p>
              <ContentGapSkeleton label={statusLine ?? "Content gap ophalen"} />
            </div>
          ) : !hasResult && blocked ? (
            <BlockedCard reason={blocked} customerId={customerId} />
          ) : !hasResult ? (
            <StartCard overview={overview} customerName={customerName} busy={busy} onStart={() => void start()} />
          ) : (
            <>
              <GapKpis overview={overview} />

              <ResultCard
                id="gap-zoekwoorden"
                title="Gap-zoekwoorden"
                description={`Posities van de concurrenten. ${customerName} staat hier niet in de top 10 – of helemaal niet.`}
              >
                {overview.found === 0 ? (
                  <EmptyResult customerName={customerName} />
                ) : overview.keywords.length === 0 ? (
                  <p className="rounded-lg border border-dashed px-4 py-5 text-[13px] text-muted-foreground">
                    Er zijn gap-zoekwoorden gevonden, maar binnen het plafond van {formatInt(overview.max_units)}{" "}
                    Ahrefs-units kon er geen enkele worden uitgewerkt.
                  </p>
                ) : (
                  <GapTable
                    keywords={overview.keywords}
                    competitors={overview.competitors}
                    customerName={customerName}
                    customerDomain={overview.customer_domain || domain}
                  />
                )}
              </ResultCard>

              <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_420px]">
                <SoonCard
                  id="per-onderwerp"
                  title="Per onderwerp"
                  description="Aantal relevante gap-zoekwoorden en gezamenlijk volume."
                  text="Claude groepeert de gap-zoekwoorden straks per onderwerp uit het klantprofiel, met het aantal en het volume per onderwerp."
                />
                <SoonCard
                  id="ai-relevantiefilter"
                  title="AI-relevantiefilter"
                  description={`Uitgesloten, omdat ${customerName} er geen dienst of klant mee wint.`}
                  text="Claude filtert straks zoekwoorden weg die niet bij de diensten van de klant passen, zoals vacatures of gratis tools; elke uitsluiting is terug te draaien."
                />
              </div>
            </>
          )}
        </>
      )}
    </div>
  )
}
