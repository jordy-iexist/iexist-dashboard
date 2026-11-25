"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { AlertTriangle, Loader2, Plus, RefreshCw, RotateCcw, Search, Users } from "lucide-react"

import { ResultCard, formatShortDate } from "@/components/klanten/analyses/result-parts"
import { AddCompetitorDialog } from "@/components/klanten/zoekwoorden/AddCompetitorDialog"
import { AiSummaryCard } from "@/components/klanten/zoekwoorden/AiSummaryCard"
import { CompetitorKpis, formatCount } from "@/components/klanten/zoekwoorden/CompetitorKpis"
import { CompetitorsTable, type CompetitorChoice } from "@/components/klanten/zoekwoorden/CompetitorsTable"
import { ConcurrentenSkeleton } from "@/components/klanten/zoekwoorden/ConcurrentenSkeleton"
import { Notice } from "@/components/klanten/zoekwoorden/Notice"
import { TopicHeatmap } from "@/components/klanten/zoekwoorden/TopicHeatmap"
import { Button } from "@/components/ui/button"
import { usePolling } from "@/hooks/use-polling"
import { contentGapHref } from "@/lib/keyword-content-gap"
import {
  KeywordCompetitorsError,
  fetchCompetitorOverview,
  isOverviewActive,
  refreshCompetitorOverview,
  removeManualCompetitor,
  saveCompetitorChoice,
  type CompetitorOverview,
  type OverviewStatus,
  type RefreshMode,
} from "@/lib/keyword-competitors"

export type ConcurrentenViewProps = {
  customerId: string
  customerName: string
  domain: string
}

const POLL_INTERVAL_MS = 3000

/** Wat er gebeurt tijdens een lopende run. */
const STATUS_LINES: Partial<Record<OverviewStatus, string>> = {
  pending: "In de wachtrij…",
  collecting: "Gegevens ophalen uit Ahrefs…",
  classifying: "Concurrenten en zoekwoorden indelen…",
  summarizing: "Samenvatting schrijven…",
}

const COUNTRY_NAMES: Record<string, string> = { nl: "Nederland", be: "België", de: "Duitsland" }

function countryName(code: string) {
  return COUNTRY_NAMES[code.toLowerCase()] ?? code.toUpperCase()
}

function errorMessage(err: unknown) {
  return err instanceof Error && err.message ? err.message : "Er ging iets mis."
}

/** Uitleg onder de titel: de basis van de concurrenten verschilt per momentopname. */
function Explanation({ overview }: { overview: CompetitorOverview | null }) {
  const country = countryName(overview?.country || "nl")
  if (overview?.fetched_at && overview.overlap_basis === "tracked") {
    return (
      <p className="text-[13px] text-muted-foreground">
        Concurrenten bepaald op basis van {formatCount(overview.tracked_sample)} gevolgde zoekwoorden uit
        ProRankTracker, omdat Ahrefs te weinig overlap kende, aangevuld met handmatig gekozen concurrenten. Database:{" "}
        {country}.
      </p>
    )
  }
  return (
    <p className="text-[13px] text-muted-foreground">
      Concurrenten automatisch bepaald op zoekwoordoverlap in Ahrefs (organische concurrenten), aangevuld met
      handmatig gekozen concurrenten. Database: {country}.
    </p>
  )
}

/** Nog geen momentopname: uitleg en de knop voor de eerste keer ophalen. */
function FirstFetchCard({
  overview,
  busy,
  onFetch,
}: {
  overview: CompetitorOverview
  busy: boolean
  onFetch: () => void
}) {
  const blocked = overview.blocked_reason !== null
  return (
    <section
      aria-labelledby="concurrenten-ophalen"
      className="flex flex-col items-center gap-3 rounded-xl border border-dashed bg-card px-6 py-10 text-center"
    >
      <span className="flex size-10 items-center justify-center rounded-full bg-muted">
        <Users className="size-5 text-muted-foreground" aria-hidden="true" />
      </span>
      <h2 id="concurrenten-ophalen" className="text-base font-semibold">
        Nog geen concurrenten opgehaald
      </h2>
      <p className="max-w-xl text-[13px] text-muted-foreground">
        Haal de organische concurrenten van {overview.domain ?? "deze klant"} op uit Ahrefs. Je krijgt per concurrent
        de sterkte en de overlap in zoekwoorden, de sterkte per onderwerp uit het klantprofiel en een samenvatting van
        Claude. Daarna wordt het overzicht elke 30 dagen vanzelf ververst.
      </p>
      {blocked && overview.blocked_message && (
        <p className="flex max-w-xl items-start gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-left text-[13px] text-amber-900 dark:border-amber-500/50 dark:bg-amber-900/20 dark:text-amber-200">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          {overview.blocked_message}
        </p>
      )}
      <Button onClick={onFetch} disabled={blocked || busy} className="mt-1 font-semibold">
        {busy ? <Loader2 className="animate-spin" aria-hidden="true" /> : <Search aria-hidden="true" />}
        {overview.status === "failed" ? "Opnieuw ophalen" : "Concurrenten ophalen"}
      </Button>
      <p className="text-xs text-muted-foreground">
        Kost naar schatting {formatCount(overview.unit_estimate)} Ahrefs-units (maximaal{" "}
        {formatCount(overview.unit_cap)}).
      </p>
    </section>
  )
}

/**
 * Zoekwoorden › Concurrenten van één klant (Figma 45 · Zoekwoorden – Concurrent-analyse).
 *
 * - Bij het openen wordt het overzicht opgehaald; zonder gegevens is de status `idle`.
 * - Zolang er een run loopt wordt het elke 3 seconden ververst; een eerdere momentopname blijft
 *   dan zichtbaar met een balk "Wordt bijgewerkt…".
 * - Keuzes per concurrent (type, uitsluiten, toevoegen, verwijderen) zijn direct zichtbaar; raken
 *   ze de vijf, dan vraagt de balk "Bijwerken" om de cijfers opnieuw te berekenen.
 */
export function ConcurrentenView({ customerId, customerName, domain }: ConcurrentenViewProps) {
  const [overview, setOverview] = useState<CompetitorOverview | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)
  const [busy, setBusy] = useState(false)
  const [busyDomain, setBusyDomain] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [actionInfo, setActionInfo] = useState<string | null>(null)
  const [dialogOpen, setDialogOpen] = useState(false)

  useEffect(() => {
    let ignore = false
    fetchCompetitorOverview(customerId)
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

  const active = overview !== null && isOverviewActive(overview.status)

  // Is de lopende run klaar, dan is de melding "er loopt al een verversing" achterhaald.
  const [wasActive, setWasActive] = useState(active)
  if (active !== wasActive) {
    setWasActive(active)
    if (!active) setActionInfo(null)
  }

  const { failing } = usePolling(
    async () => {
      setOverview(await fetchCompetitorOverview(customerId))
    },
    active,
    POLL_INTERVAL_MS
  )

  async function reload() {
    const latest = await fetchCompetitorOverview(customerId).catch(() => null)
    if (latest) setOverview(latest)
  }

  async function refresh(mode: RefreshMode) {
    setBusy(true)
    setActionError(null)
    setActionInfo(null)
    try {
      setOverview(await refreshCompetitorOverview(customerId, mode))
    } catch (err) {
      // 409 = er loopt al een verversing: de actuele stand tonen (de polling neemt het over).
      if (err instanceof KeywordCompetitorsError && err.status === 409) {
        setActionInfo("Er loopt al een verversing; de stand hieronder wordt vanzelf bijgewerkt.")
      } else {
        setActionError(errorMessage(err))
      }
      await reload()
    } finally {
      setBusy(false)
    }
  }

  async function mutateRow(domainName: string, run: () => Promise<CompetitorOverview>) {
    setBusyDomain(domainName)
    setActionError(null)
    setActionInfo(null)
    try {
      setOverview(await run())
    } catch (err) {
      setActionError(errorMessage(err))
      await reload()
    } finally {
      setBusyDomain(null)
    }
  }

  function saveChoice(choice: CompetitorChoice) {
    void mutateRow(choice.domain, () => saveCompetitorChoice(customerId, choice))
  }

  function removeCompetitor(domainName: string) {
    void mutateRow(domainName, () => removeManualCompetitor(customerId, domainName))
  }

  const hasSnapshot = overview?.fetched_at != null
  const statusLine = overview ? STATUS_LINES[overview.status] : undefined
  const fetchedAt = formatShortDate(overview?.fetched_at)
  const refreshDisabled = !overview || !hasSnapshot || active || busy || overview.blocked_reason !== null
  const rowsDisabled = busy || busyDomain !== null

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0 max-w-3xl space-y-1">
          <p className="text-[13px] text-muted-foreground">
            Zoekwoorden <span aria-hidden="true">/</span> {customerName}
          </p>
          <h1 className="text-2xl font-bold tracking-tight break-words sm:text-[28px]">Concurrenten</h1>
          <Explanation overview={overview} />
          <p className="text-xs text-muted-foreground">
            <span className="break-all">{overview?.domain ?? domain}</span>
            {fetchedAt && (
              <>
                {` · Bijgewerkt op ${fetchedAt}`}
                {` · ${formatCount(overview?.units)} Ahrefs-units`}
              </>
            )}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span
            title={
              active
                ? "Er loopt al een verversing; wacht tot die klaar is."
                : overview && hasSnapshot
                  ? `Haalt alles opnieuw op uit Ahrefs (naar schatting ${formatCount(overview.unit_estimate)} units).`
                  : undefined
            }
          >
            <Button variant="outline" onClick={() => void refresh("full")} disabled={refreshDisabled}>
              {active || busy ? (
                <Loader2 className="animate-spin" aria-hidden="true" />
              ) : (
                <RefreshCw aria-hidden="true" />
              )}
              Vernieuwen
            </Button>
          </span>
          <Button variant="outline" onClick={() => setDialogOpen(true)} disabled={!overview}>
            <Plus aria-hidden="true" />
            Concurrent toevoegen
          </Button>
          {/* Opent het Content gap-scherm; starten (en units uitgeven) gebeurt daar. */}
          {hasSnapshot ? (
            <Button asChild className="font-semibold">
              <Link href={contentGapHref(customerId)}>Content gap starten</Link>
            </Button>
          ) : (
            // Een uitgeschakelde knop krijgt geen muisgebeurtenissen; de uitleg staat op de omhulling.
            <span
              title={
                overview
                  ? "Haal eerst de concurrenten op: de content gap bouwt voort op een voltooide concurrentenscan."
                  : undefined
              }
            >
              <Button disabled className="font-semibold">
                Content gap starten
              </Button>
            </span>
          )}
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
          De concurrenten konden niet worden opgehaald: {loadError}
        </Notice>
      ) : !overview ? (
        <ConcurrentenSkeleton />
      ) : (
        <>
          {(actionError ||
            actionInfo ||
            failing ||
            (hasSnapshot && overview.blocked_message) ||
            (overview.status === "failed" && overview.error_message) ||
            overview.warnings.length > 0 ||
            (active && hasSnapshot) ||
            (overview.dirty && !active)) && (
            <div className="space-y-2">
              {actionError && <Notice tone="red">{actionError}</Notice>}
              {actionInfo && <Notice tone="neutral">{actionInfo}</Notice>}
              {failing && (
                <Notice tone="amber">
                  De stand wordt niet meer bijgewerkt. Controleer je verbinding; we blijven het proberen.
                </Notice>
              )}
              {/* Zonder momentopname staat deze melding bij de knop "Concurrenten ophalen". */}
              {hasSnapshot && overview.blocked_message && <Notice tone="amber">{overview.blocked_message}</Notice>}
              {overview.status === "failed" && overview.error_message && (
                <Notice tone="red">
                  {hasSnapshot ? "De laatste verversing is mislukt: " : "Ophalen is mislukt: "}
                  {overview.error_message}
                  {hasSnapshot && fetchedAt && (
                    <span className="mt-0.5 block text-xs">De cijfers hieronder zijn van {fetchedAt}.</span>
                  )}
                </Notice>
              )}
              {overview.warnings.map((warning, index) => (
                <Notice key={index} tone="amber">
                  {warning}
                </Notice>
              ))}
              {active && hasSnapshot && (
                <Notice tone="neutral" icon={<Loader2 className="size-4 shrink-0 animate-spin" aria-hidden="true" />}>
                  <span className="font-medium">Wordt bijgewerkt…</span>
                  {statusLine && <span className="text-muted-foreground"> {statusLine}</span>}
                </Notice>
              )}
              {overview.dirty && !active && (
                <Notice
                  tone="neutral"
                  action={
                    <Button
                      size="sm"
                      onClick={() => void refresh("reuse")}
                      disabled={busy || overview.blocked_reason !== null}
                    >
                      {busy ? <Loader2 className="animate-spin" aria-hidden="true" /> : <RefreshCw aria-hidden="true" />}
                      Bijwerken
                    </Button>
                  }
                >
                  Je hebt concurrenten gewijzigd. Werk het overzicht bij om de cijfers, de heatmap en de samenvatting aan
                  te passen.
                </Notice>
              )}
            </div>
          )}

          {!hasSnapshot && active ? (
            <div className="space-y-3">
              <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="size-4 shrink-0 animate-spin" aria-hidden="true" />
                {statusLine ?? "Bezig…"}
              </p>
              <ConcurrentenSkeleton label={statusLine ?? "Concurrenten ophalen"} />
            </div>
          ) : !hasSnapshot ? (
            <>
              <FirstFetchCard overview={overview} busy={busy} onFetch={() => void refresh("full")} />
              {overview.competitors.rows.length > 0 && (
                <ResultCard
                  id="handmatige-concurrenten"
                  title="Toegevoegde concurrenten"
                  description="Deze domeinen krijgen cijfers zodra de concurrenten zijn opgehaald."
                >
                  <CompetitorsTable
                    section={overview.competitors}
                    overlapBasis={overview.overlap_basis}
                    trackedSample={overview.tracked_sample}
                    busyDomain={busyDomain}
                    disabled={rowsDisabled}
                    onChoice={saveChoice}
                    onRemove={removeCompetitor}
                  />
                </ResultCard>
              )}
            </>
          ) : (
            <>
              <CompetitorKpis
                kpis={overview.kpis}
                customerName={customerName}
                overlapBasis={overview.overlap_basis}
                trackedSample={overview.tracked_sample}
              />

              <ResultCard
                id="wie-concurreert"
                title="Wie concurreert er in Google?"
                description="Gesorteerd op overlap. Vergelijkingssites worden herkend en uitgesloten van de gap-analyse."
              >
                <CompetitorsTable
                  section={overview.competitors}
                  overlapBasis={overview.overlap_basis}
                  trackedSample={overview.tracked_sample}
                  busyDomain={busyDomain}
                  disabled={rowsDisabled}
                  onChoice={saveChoice}
                  onRemove={removeCompetitor}
                />
              </ResultCard>

              <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
                <TopicHeatmap heatmap={overview.heatmap} customerId={customerId} />
                <AiSummaryCard summary={overview.summary} />
              </div>
            </>
          )}
        </>
      )}

      <AddCompetitorDialog
        customerId={customerId}
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        onAdded={(next) => {
          setActionError(null)
          setOverview(next)
        }}
      />
    </div>
  )
}
