"use client"

import { useCallback, useEffect, useState } from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { CircleAlert, FileText, Loader2, Plus, RotateCcw, TriangleAlert } from "lucide-react"

import { ActionsCard } from "@/components/klanten/analyses/ActionsCard"
import { AiOverviewCard } from "@/components/klanten/analyses/AiOverviewCard"
import { AnalysisProgress } from "@/components/klanten/analyses/AnalysisProgress"
import { AnalysisStatusPill } from "@/components/klanten/analyses/AnalysisStatusPill"
import { ComparisonTable } from "@/components/klanten/analyses/ComparisonTable"
import { EeatCard } from "@/components/klanten/analyses/EeatCard"
import { MissingTopicsCard } from "@/components/klanten/analyses/MissingTopicsCard"
import { PaaCard } from "@/components/klanten/analyses/PaaCard"
import { formatEur, formatInt, formatShortDate, formatUsd, type ResultCardState } from "@/components/klanten/analyses/result-parts"
import { PanelTabs, Pill, PollingFailedNotice } from "@/components/livegang/shared"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { usePolling } from "@/hooks/use-polling"
import {
  CompetitorAnalysisError,
  KEYWORD_PARAM,
  POSITION_SOURCE_LABELS,
  analysesHref,
  cancelAnalysis,
  cardState,
  countryLabel,
  fetchAnalysis,
  fetchKeywordDetail,
  isActive,
  newAnalysisHref,
  type AiState,
  type AnalysisDetail,
  type KeywordDetail,
  type KeywordSummary,
  type SourceState,
} from "@/lib/competitor-analysis"
import { briefHref, startBrief } from "@/lib/content-brief"
import { writeUrlParams } from "@/lib/url-state"
import { cn } from "@/lib/utils"

export type AnalysisResultProps = {
  customerId: string
  customerName: string
  /** Domein van de klant zonder protocol, bijv. "iexist.nl". */
  customerDomain: string
  /** Volledige URL van de klantsite, bijv. "https://www.iexist.nl". */
  customerBaseUrl: string
  analysisId: string
  /** Zoekwoord-id uit `?zoekwoord=`; null = het eerste zoekwoord van de analyse. */
  initialKeywordId: string | null
}

const POLL_INTERVAL_MS = 3000

/** Google-domein per land voor de regel onder de titel. */
const GOOGLE_DOMAINS: Record<string, string> = {
  nl: "Google.nl",
  be: "Google.be",
  de: "Google.de",
  fr: "Google.fr",
  gb: "Google.co.uk",
  us: "Google.com",
}

/** Ahrefs-intenties in gewone taal. */
const INTENT_LABELS: Record<string, string> = {
  informational: "Informatief",
  navigational: "Navigerend",
  commercial: "Commercieel",
  transactional: "Transactioneel",
  branded: "Merk",
  local: "Lokaal",
}

/** Ahrefs-SERP-featuretypes in gewone taal; onbekende types worden leesbaar gemaakt. */
const SERP_FEATURE_LABELS: Record<string, string> = {
  ai_overview: "AI Overview",
  ai_overview_sitelink: "AI Overview",
  featured_snippet: "Featured snippet",
  local_pack: "Local pack",
  question: "Mensen vragen ook",
  people_also_ask: "Mensen vragen ook",
  sitelink: "Sitelinks",
  image: "Afbeeldingen",
  image_th: "Afbeeldingen",
  video: "Video's",
  video_th: "Video's",
  top_story: "Topverhalen",
  top_stories: "Topverhalen",
  knowledge_card: "Knowledge card",
  knowledge_panel: "Knowledge panel",
  discussion: "Discussies en forums",
  shopping: "Shopping",
  paid_top: "Advertenties",
  paid_bottom: "Advertenties",
  paid_right: "Advertenties",
  paid_sitelink: "Advertenties",
  tweet: "X-berichten",
}

function serpFeatureLabel(type: string) {
  if (SERP_FEATURE_LABELS[type]) return SERP_FEATURE_LABELS[type]
  const text = type.replace(/_/g, " ").trim()
  return text.charAt(0).toUpperCase() + text.slice(1)
}

function unique(values: string[]) {
  return [...new Set(values)]
}

function errorMessage(err: unknown) {
  return err instanceof Error && err.message ? err.message : "Er ging iets mis."
}

// --- Kop ------------------------------------------------------------------------------------

function ResultHeader({
  customerId,
  customerName,
  analysis,
  keyword,
  detail,
  showSerp,
  briefError,
  onBriefError,
}: {
  customerId: string
  customerName: string
  analysis: AnalysisDetail
  keyword: KeywordSummary | null
  detail: KeywordDetail | null
  showSerp: boolean
  briefError: string | null
  onBriefError: (message: string | null) => void
}) {
  const info = detail ?? keyword
  const targetUrl = detail ? detail.target_url : (keyword?.target_url ?? null)
  const positionSource = detail?.own_position_source

  const meta: React.ReactNode[] = []
  if (info) {
    if (info.own_position != null) {
      meta.push(
        <span key="pos" title={positionSource ? `Bron: ${POSITION_SOURCE_LABELS[positionSource]}` : undefined}>
          Positie {info.own_position}
        </span>
      )
    } else {
      meta.push(<span key="pos">{targetUrl ? "Positie onbekend" : "Nog geen pagina"}</span>)
    }
    if (info.volume != null) meta.push(<span key="vol">{formatInt(info.volume)} /mnd</span>)
    if (info.kd != null) meta.push(<span key="kd" title="Keyword Difficulty (Ahrefs)">KD {info.kd}</span>)
  }
  meta.push(
    <span key="country">
      {GOOGLE_DOMAINS[analysis.country.toLowerCase()] ?? "Google"}, {countryLabel(analysis.country)}
    </span>
  )
  const completed = formatShortDate(analysis.completed_at)
  const started = formatShortDate(analysis.created_at)
  if (completed) meta.push(<span key="date">geanalyseerd {completed}</span>)
  else if (started) meta.push(<span key="date">gestart {started}</span>)

  const intents = unique((detail?.intents ?? []).map((intent) => INTENT_LABELS[intent] ?? intent))
  const features = showSerp ? unique((detail?.serp_features ?? []).map(serpFeatureLabel)) : []
  const searchIntent = detail?.search_intent?.trim()

  return (
    <header className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <BackLink customerId={customerId} customerName={customerName} />
        <div className="flex flex-wrap items-center gap-2">
          {analysis.status !== "completed" && <AnalysisStatusPill status={analysis.status} />}
          {keyword && (
            <BriefButton
              key={keyword.id}
              customerId={customerId}
              analysisId={analysis.id}
              keyword={keyword}
              onError={onBriefError}
            />
          )}
        </div>
      </div>

      {briefError && <ErrorBlock>De content brief kon niet worden gestart: {briefError}</ErrorBlock>}

      <h1 className="text-2xl font-bold tracking-tight break-words sm:text-3xl">
        {info ? `“${info.keyword}”` : "Concurrentieanalyse"}
      </h1>

      <p className="flex flex-wrap gap-x-1.5 text-sm text-muted-foreground">
        {meta.map((part, index) => (
          <span key={index} className="inline-flex gap-x-1.5">
            {index > 0 && <span aria-hidden="true">·</span>}
            {part}
          </span>
        ))}
      </p>

      {detail?.serp_summary && <p className="max-w-3xl text-[15px] leading-relaxed">{detail.serp_summary}</p>}

      {(searchIntent || intents.length > 0 || features.length > 0) && (
        <div className="flex flex-wrap items-center gap-1.5">
          {(searchIntent || intents.length > 0) && <span className="text-xs text-muted-foreground">Zoekintentie:</span>}
          {searchIntent && <Pill tone="blue">{searchIntent}</Pill>}
          {!searchIntent && intents.map((intent) => <Pill key={intent} tone="blue">{intent}</Pill>)}
          {features.length > 0 && (
            <span className={cn("text-xs text-muted-foreground", (searchIntent || intents.length > 0) && "ml-2")}>
              In de zoekresultaten:
            </span>
          )}
          {features.map((feature) => (
            <Pill key={feature}>{feature}</Pill>
          ))}
        </div>
      )}
    </header>
  )
}

// --- Content brief --------------------------------------------------------------------------

/**
 * Knop naar de content brief van het gekozen zoekwoord. Zonder brief start hij de brief en opent
 * daarna het scherm; een 409 (bestaat al of loopt al) is geen fout. Alleen voor afgeronde zoekwoorden.
 */
function BriefButton({
  customerId,
  analysisId,
  keyword,
  onError,
}: {
  customerId: string
  analysisId: string
  keyword: KeywordSummary
  onError: (message: string | null) => void
}) {
  const router = useRouter()
  const [starting, setStarting] = useState(false)
  const href = briefHref(customerId, analysisId, keyword.id)
  const ready = keyword.status === "completed"

  if (keyword.brief_status) {
    return (
      <Button asChild size="sm">
        <Link href={href}>
          <FileText />
          Content brief bekijken
        </Link>
      </Button>
    )
  }

  async function start() {
    setStarting(true)
    onError(null)
    try {
      await startBrief(analysisId, keyword.id)
      router.push(href)
    } catch (err) {
      if (err instanceof CompetitorAnalysisError && err.status === 409) {
        router.push(href)
      } else {
        onError(errorMessage(err))
        setStarting(false)
      }
    }
  }

  return (
    // Een uitgeschakelde knop krijgt geen muisgebeurtenissen; de uitleg staat op de omhulling.
    <span
      title={
        ready
          ? undefined
          : keyword.status === "failed"
            ? "Dit zoekwoord kon niet worden geanalyseerd, dus er is geen basis voor een content brief."
            : "Kan pas als de analyse van dit zoekwoord klaar is."
      }
    >
      <Button size="sm" onClick={start} disabled={!ready || starting}>
        {starting ? <Loader2 className="animate-spin" aria-hidden="true" /> : <FileText />}
        Content brief maken
      </Button>
    </span>
  )
}

// --- Meldingen ------------------------------------------------------------------------------

function Warning({ children }: { children: React.ReactNode }) {
  return (
    <p className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:bg-amber-900/20 dark:text-amber-200">
      <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <span>{children}</span>
    </p>
  )
}

function ErrorBlock({ children, action }: { children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div role="alert" className="flex flex-wrap items-center gap-3 rounded-md border border-red-300 bg-card px-3 py-2 text-sm text-red-700 dark:text-red-300">
      <CircleAlert className="size-4 shrink-0" aria-hidden="true" />
      <span className="min-w-0 flex-1">{children}</span>
      {action}
    </div>
  )
}

function NewAnalysisButton({ customerId, keywords }: { customerId: string; keywords: string[] }) {
  return (
    <Button asChild size="sm" variant="outline" className="font-semibold">
      <Link href={newAnalysisHref(customerId, keywords)}>
        <Plus />
        Nieuwe analyse
      </Link>
    </Button>
  )
}

/** Verbruik naast de schatting, als bescheiden regel onderaan. */
function UsageLine({ analysis }: { analysis: AnalysisDetail }) {
  const { estimate, ai_usage: usage } = analysis
  const ahrefs = `${formatInt(analysis.ahrefs_units)} Ahrefs-units${estimate ? ` (geschat ${formatInt(estimate.ahrefs_units)})` : ""}`
  const claude = usage
    ? `Claude ${formatUsd(usage.cost_usd)} in ${usage.calls} ${usage.calls === 1 ? "aanroep" : "aanroepen"}`
    : isActive(analysis.status)
      ? "Claude nog niet gebruikt"
      : "Claude niet gebruikt"
  const claudeEstimate = estimate ? ` (geschat ${formatEur(estimate.ai_cost_eur)})` : ""
  return (
    <p className="text-xs text-muted-foreground">
      Verbruik{isActive(analysis.status) ? " tot nu toe" : ""}: {ahrefs} · {claude}
      {claudeEstimate}
    </p>
  )
}

// --- Hoofdcomponent -------------------------------------------------------------------------

/**
 * Voortgang en resultaat van een analyse (Figma 03, node 1:140).
 *
 * Laden en verversen:
 * - De analyse (status, tellers, zoekwoorden) wordt bij het openen opgehaald en daarna elke
 *   3 seconden zolang hij loopt (`usePolling`).
 * - Het detail van het gekozen zoekwoord wordt opgehaald bij het kiezen van een zoekwoord en in
 *   dezelfde pollronde ververst, direct na de analyse. De ronde die de afgeronde status ziet,
 *   ververst het detail dus nog één keer; daarna stopt het pollen.
 * - Details worden per zoekwoord bewaard, zodat een late respons voor een ander zoekwoord het
 *   gekozen zoekwoord niet overschrijft.
 */
export function AnalysisResult({ customerId, customerName, customerDomain, analysisId, initialKeywordId }: AnalysisResultProps) {
  const [analysis, setAnalysis] = useState<AnalysisDetail | null>(null)
  const [loadError, setLoadError] = useState<{ message: string; status: number } | null>(null)
  const [loadAttempt, setLoadAttempt] = useState(0)
  const [chosenKeywordId, setChosenKeywordId] = useState<string | null>(initialKeywordId)
  const [details, setDetails] = useState<Record<string, KeywordDetail>>({})
  const [detailErrors, setDetailErrors] = useState<Record<string, string>>({})
  const [detailAttempt, setDetailAttempt] = useState(0)
  const [canceling, setCanceling] = useState(false)
  const [cancelError, setCancelError] = useState<string | null>(null)
  const [briefError, setBriefError] = useState<string | null>(null)

  // De analyse ophalen bij het openen (en bij "Opnieuw proberen").
  useEffect(() => {
    let ignore = false
    fetchAnalysis(analysisId)
      .then((next) => {
        if (ignore) return
        setAnalysis(next)
        setLoadError(null)
      })
      .catch((err: unknown) => {
        if (ignore) return
        setLoadError({
          message: errorMessage(err),
          status: err instanceof CompetitorAnalysisError ? err.status : 0,
        })
      })
    return () => {
      ignore = true
    }
  }, [analysisId, loadAttempt])

  const keywords = analysis?.keywords ?? []
  const selected = keywords.find((keyword) => keyword.id === chosenKeywordId) ?? keywords[0] ?? null
  const selectedId = selected?.id ?? null

  const loadDetail = useCallback(
    async (keywordId: string) => {
      try {
        const next = await fetchKeywordDetail(analysisId, keywordId)
        setDetails((current) => ({ ...current, [keywordId]: next }))
        setDetailErrors((current) => {
          if (!(keywordId in current)) return current
          const rest = { ...current }
          delete rest[keywordId]
          return rest
        })
      } catch (err) {
        setDetailErrors((current) => ({ ...current, [keywordId]: errorMessage(err) }))
        throw err
      }
    },
    [analysisId]
  )

  // Detail van het gekozen zoekwoord ophalen bij het kiezen (en bij "Opnieuw proberen").
  useEffect(() => {
    if (!selectedId) return
    loadDetail(selectedId).catch(() => {
      // de fout staat in detailErrors
    })
  }, [selectedId, loadDetail, detailAttempt])

  const active = analysis !== null && isActive(analysis.status)

  // Zolang de analyse loopt: status en het gekozen zoekwoord elke 3 seconden verversen.
  const { failing } = usePolling(
    async () => {
      const next = await fetchAnalysis(analysisId)
      setAnalysis(next)
      if (selectedId) await loadDetail(selectedId)
    },
    active,
    POLL_INTERVAL_MS
  )

  function selectKeyword(keywordId: string) {
    setChosenKeywordId(keywordId)
    setBriefError(null)
    writeUrlParams({ [KEYWORD_PARAM]: keywordId })
  }

  async function cancel() {
    if (!analysis) return
    if (!window.confirm("Deze analyse annuleren? Wat al klaar is, blijft zichtbaar.")) return
    setCanceling(true)
    setCancelError(null)
    try {
      setAnalysis(await cancelAnalysis(analysis.id))
    } catch (err) {
      setCancelError(errorMessage(err))
      // Bijv. 409: de analyse is intussen al afgerond. Toon de actuele stand.
      const latest = await fetchAnalysis(analysis.id).catch(() => null)
      if (latest) setAnalysis(latest)
    } finally {
      setCanceling(false)
    }
    // Het pollen stopt nu; het detail nog één keer verversen.
    if (selectedId) loadDetail(selectedId).catch(() => {})
  }

  // --- Laden, niet gevonden, fout ---

  if (!analysis) {
    if (loadError?.status === 404) {
      return (
        <div className="space-y-6">
          <BackLink customerId={customerId} customerName={customerName} />
          <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed bg-card px-6 py-10 text-center">
            <p className="text-base font-semibold">Analyse niet gevonden</p>
            <p className="max-w-md text-sm text-muted-foreground">
              Deze analyse bestaat niet (meer) of hoort bij een andere klant.
            </p>
            <Button asChild variant="outline">
              <Link href={analysesHref(customerId)}>Naar de analyses</Link>
            </Button>
          </div>
        </div>
      )
    }
    if (loadError) {
      return (
        <div className="space-y-6">
          <BackLink customerId={customerId} customerName={customerName} />
          <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed bg-card px-6 py-10 text-center">
            <p className="text-sm text-muted-foreground">De analyse kon niet worden opgehaald: {loadError.message}</p>
            <Button variant="outline" onClick={() => setLoadAttempt((value) => value + 1)}>
              <RotateCcw />
              Opnieuw proberen
            </Button>
          </div>
        </div>
      )
    }
    return (
      <div className="space-y-6" aria-busy="true">
        <BackLink customerId={customerId} customerName={customerName} />
        <p role="status" className="sr-only">
          Analyse laden…
        </p>
        <div className="space-y-3">
          <Skeleton className="h-9 w-72" />
          <Skeleton className="h-4 w-96 max-w-full" />
        </div>
        <Skeleton className="h-64 w-full rounded-xl" />
      </div>
    )
  }

  // --- Resultaat ---

  const modules = analysis.modules
  const showSerp = modules.includes("serp")
  const showTopics = modules.includes("topics")
  const showEeat = modules.includes("eeat")
  const showActions = showTopics || showEeat
  const keywordTexts = keywords.map((keyword) => keyword.keyword)

  const detail = selectedId ? (details[selectedId] ?? null) : null
  const detailError = selectedId ? (detailErrors[selectedId] ?? null) : null
  const keywordStatus = detail?.status ?? selected?.status ?? "pending"
  const keywordError = detail?.error_message ?? selected?.error_message ?? null
  // Na annuleren of mislukken blijven onafgemaakte zoekwoorden op "pending": dan niet "bezig".
  const keywordRunning = active && keywordStatus === "pending"
  const stoppedEarly = !active && keywordStatus === "pending"
  const stoppedMessage =
    analysis.status === "canceled"
      ? "De analyse is geannuleerd voordat dit onderdeel klaar was."
      : analysis.status === "failed"
        ? "De analyse is gestopt voordat dit onderdeel klaar was."
        : null

  /** Toestand van een kaart uit de gegevens, de bron en de voortgang van het zoekwoord. */
  function stateFor(hasData: boolean, source: SourceState | AiState | null | undefined): ResultCardState {
    if (hasData) return "filled"
    if (keywordFailedOrStopped() && source == null) return "unavailable"
    if (keywordRunning && (source == null || source === "skipped")) return "pending"
    return cardState(source, false)
  }
  function keywordFailedOrStopped() {
    return keywordStatus === "failed" || stoppedEarly
  }
  const stoppedError = keywordStatus === "failed" ? keywordError : stoppedEarly ? stoppedMessage : null

  const tableHasData = Boolean(detail && (detail.pages.length > 0 || detail.own))
  const tableState: ResultCardState = tableHasData
    ? "filled"
    : keywordRunning
      ? "pending"
      : keywordFailedOrStopped()
        ? "unavailable"
        : cardState(analysis.sources.ahrefs.state, false)

  const aiError = detail?.ai_error ?? stoppedError

  const sideCards: React.ReactNode[] = []
  if (detail && showTopics) {
    sideCards.push(
      <MissingTopicsCard
        key="topics"
        topics={detail.missing_topics}
        state={stateFor(detail.missing_topics.length > 0, detail.ai_state)}
        error={aiError}
        hasOwnPage={detail.target_url !== null}
      />
    )
  }
  if (detail && showSerp) {
    sideCards.push(
      <PaaCard
        key="paa"
        questions={detail.paa?.questions ?? []}
        state={stateFor((detail.paa?.questions.length ?? 0) > 0, detail.paa?.state)}
      />,
      <AiOverviewCard
        key="ai-overview"
        aiOverview={detail.ai_overview}
        state={stateFor((detail.ai_overview?.sources.length ?? 0) > 0, detail.ai_overview?.state)}
        customerDomain={customerDomain}
      />
    )
  }

  const eeatHasData = Boolean(detail && (detail.own?.eeat || detail.pages.some((page) => page.eeat)))

  return (
    <div className="space-y-6">
      <ResultHeader
        customerId={customerId}
        customerName={customerName}
        analysis={analysis}
        keyword={selected}
        detail={detail}
        showSerp={showSerp}
        briefError={briefError}
        onBriefError={setBriefError}
      />

      {keywords.length > 1 && (
        <nav aria-label="Zoekwoorden in deze analyse">
          <PanelTabs
            tabs={keywords.map((keyword) => ({
              key: keyword.id,
              label: <KeywordTabLabel keyword={keyword} analysisActive={active} />,
            }))}
            active={selectedId ?? ""}
            onSelect={selectKeyword}
          />
        </nav>
      )}

      {analysis.warnings.length > 0 && (
        <div className="space-y-2">
          {analysis.warnings.map((warning) => (
            <Warning key={warning}>{warning}</Warning>
          ))}
        </div>
      )}

      {active && <AnalysisProgress analysis={analysis} canceling={canceling} onCancel={cancel} />}
      <PollingFailedNotice failing={failing} />
      {cancelError && <ErrorBlock>{cancelError}</ErrorBlock>}

      {analysis.status === "failed" && (
        <ErrorBlock action={<NewAnalysisButton customerId={customerId} keywords={keywordTexts} />}>
          De analyse is mislukt: {analysis.error_message?.trim() || "onbekende fout"}. Wat wel is afgerond, staat hieronder.
        </ErrorBlock>
      )}
      {analysis.status === "canceled" && (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border bg-card px-4 py-3 text-sm text-muted-foreground">
          <span className="min-w-0 flex-1">Deze analyse is geannuleerd. Wat al klaar was, staat hieronder.</span>
          <NewAnalysisButton customerId={customerId} keywords={keywordTexts} />
        </div>
      )}

      {keywordStatus === "failed" && (
        <ErrorBlock>
          Dit zoekwoord kon niet worden geanalyseerd{keywordError ? `: ${keywordError}` : "."}
        </ErrorBlock>
      )}

      {keywords.length === 0 ? (
        !active && (
          <p className="rounded-lg border border-dashed bg-card px-4 py-6 text-center text-sm text-muted-foreground">
            Deze analyse heeft geen zoekwoorden.
          </p>
        )
      ) : !detail ? (
        detailError ? (
          <ErrorBlock
            action={
              <Button size="sm" variant="outline" onClick={() => setDetailAttempt((value) => value + 1)}>
                <RotateCcw />
                Opnieuw proberen
              </Button>
            }
          >
            Het resultaat van dit zoekwoord kon niet worden opgehaald: {detailError}
          </ErrorBlock>
        ) : (
          <div aria-busy="true" className="space-y-6">
            <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" aria-hidden="true" />
              Resultaat laden…
            </p>
            <Skeleton className="h-72 w-full rounded-xl" />
          </div>
        )
      ) : (
        <>
          <ComparisonTable
            key={`table-${detail.id}`}
            detail={detail}
            modules={modules}
            topN={analysis.top_n}
            running={keywordRunning}
            tableState={tableState}
            error={keywordStatus === "failed" ? keywordError : stoppedError}
          />

          {(showActions || sideCards.length > 0) && (
            <div
              className={cn(
                "grid items-start gap-6",
                showActions && sideCards.length > 0 && "lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]",
                !showActions && "md:grid-cols-2 xl:grid-cols-3"
              )}
            >
              {showActions && (
                <ActionsCard
                  key={`actions-${detail.id}`}
                  actions={detail.actions}
                  state={stateFor(detail.actions.length > 0, detail.ai_state)}
                  error={aiError}
                />
              )}
              {showActions ? sideCards.length > 0 && <div className="grid gap-6">{sideCards}</div> : sideCards}
            </div>
          )}

          {showEeat && (
            <EeatCard
              pages={detail.pages}
              own={detail.own}
              state={stateFor(eeatHasData, detail.ai_state)}
              error={aiError}
            />
          )}
        </>
      )}

      <UsageLine analysis={analysis} />
    </div>
  )
}

function BackLink({ customerId, customerName }: { customerId: string; customerName: string }) {
  return (
    <nav aria-label="Kruimelpad">
      <ol className="flex flex-wrap items-center gap-1.5 text-sm text-muted-foreground">
        <li>
          <Link href={analysesHref(customerId)} className="underline-offset-2 hover:text-foreground hover:underline">
            Analyses
          </Link>
        </li>
        <li aria-hidden="true">/</li>
        <li>{customerName}</li>
      </ol>
    </nav>
  )
}

/** Zoekwoord in de kiezer, met een teken als het nog loopt, mislukt of niet is afgerond. */
function KeywordTabLabel({ keyword, analysisActive }: { keyword: KeywordSummary; analysisActive: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      {keyword.keyword}
      {keyword.status === "failed" && (
        <>
          <CircleAlert className="size-3.5 text-red-600 dark:text-red-400" aria-hidden="true" />
          <span className="sr-only">(mislukt)</span>
        </>
      )}
      {keyword.status === "pending" &&
        (analysisActive ? (
          <>
            <Loader2 className="size-3.5 animate-spin text-muted-foreground" aria-hidden="true" />
            <span className="sr-only">(bezig)</span>
          </>
        ) : (
          <span className="text-xs text-muted-foreground">(niet afgerond)</span>
        ))}
    </span>
  )
}
