"use client"

import { useEffect, useRef, useState } from "react"
import Link from "next/link"
import { Check, CircleAlert, Copy, FileText, Loader2, RotateCcw } from "lucide-react"

import { BriefCard } from "@/components/klanten/analyses/brief/BriefCard"
import { ConceptCard, ConceptCopyText, conceptMarkdown } from "@/components/klanten/analyses/brief/ConceptCard"
import { formatShortDate, formatUsd, ResultCard } from "@/components/klanten/analyses/result-parts"
import { Pill, PollingFailedNotice } from "@/components/livegang/shared"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { usePolling } from "@/hooks/use-polling"
import { customerHref } from "@/lib/active-customer"
import {
  CompetitorAnalysisError,
  analysesHref,
  analysisHref,
  fetchAnalysis,
  type AnalysisDetail,
} from "@/lib/competitor-analysis"
import {
  fetchBrief,
  isBriefActive,
  regenerateConcept,
  startBrief,
  type ContentBrief,
  type ContentBriefStatus,
} from "@/lib/content-brief"

export type ContentBriefViewProps = {
  customerId: string
  customerName: string
  analysisId: string
  /** Zoekwoord-id uit `?zoekwoord=`; null = niet opgegeven. */
  keywordId: string | null
}

const POLL_INTERVAL_MS = 3000

const STATUS_TEXT: Record<ContentBriefStatus, string> = {
  pending: "in de wachtrij",
  brief: "brief wordt opgesteld",
  concept: "concepttekst wordt geschreven",
  completed: "concept – wacht op review",
  failed: "mislukt",
}

const NOT_READY_TEXT = "Dit kan pas als de analyse van dit zoekwoord klaar is."

type LoadError = { message: string; status: number }

function errorMessage(err: unknown) {
  return err instanceof Error && err.message ? err.message : "Er ging iets mis."
}

function toLoadError(err: unknown): LoadError {
  return { message: errorMessage(err), status: err instanceof CompetitorAnalysisError ? err.status : 0 }
}

/** Pad van de doelpagina ("/seo"); de hele URL als die niet te lezen is. */
function targetPath(url: string) {
  try {
    const path = new URL(url).pathname
    return path.length > 1 ? path.replace(/\/+$/, "") : "/"
  } catch {
    return url
  }
}

/** Welke stap loopt er: de brief, of (als die er al is) de concepttekst. */
function runningLabel(brief: ContentBrief) {
  if (brief.status === "concept" || (brief.status === "pending" && brief.brief !== null)) {
    return "Concepttekst wordt geschreven…"
  }
  return "Brief wordt opgesteld…"
}

// --- Kleine onderdelen ----------------------------------------------------------------------

function Breadcrumb({
  customerId,
  customerName,
  analysisId,
  keywordId,
  keyword,
}: {
  customerId: string
  customerName: string
  analysisId: string
  keywordId: string | null
  keyword: string | null
}) {
  const linkClass = "underline-offset-2 hover:text-foreground hover:underline"
  return (
    <nav aria-label="Kruimelpad">
      <ol className="flex flex-wrap items-center gap-1.5 text-[13px] text-muted-foreground">
        <li>
          <Link href={customerHref("home", customerId)} className={linkClass}>
            {customerName}
          </Link>
        </li>
        <li aria-hidden="true">/</li>
        <li>
          <Link href={analysesHref(customerId)} className={linkClass}>
            Concurrentieanalyse
          </Link>
        </li>
        {keyword && (
          <>
            <li aria-hidden="true">/</li>
            <li className="min-w-0 break-words">
              <Link href={analysisHref(customerId, analysisId, keywordId)} className={linkClass}>
                “{keyword}”
              </Link>
            </li>
          </>
        )}
        <li aria-hidden="true">/</li>
        <li aria-current="page" className="text-foreground">
          Content brief
        </li>
      </ol>
    </nav>
  )
}

function ErrorBlock({ children, action }: { children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center gap-3 rounded-md border border-red-300 bg-card px-3 py-2 text-sm text-red-700 dark:text-red-300"
    >
      <CircleAlert className="size-4 shrink-0" aria-hidden="true" />
      <span className="min-w-0 flex-1">{children}</span>
      {action}
    </div>
  )
}

/** Melding in plaats van de inhoud (niet gevonden, ontbrekend zoekwoord, laadfout). */
function Notice({ title, children, action }: { title?: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed bg-card px-6 py-10 text-center">
      {title && <p className="text-base font-semibold">{title}</p>}
      <div className="max-w-md text-sm text-muted-foreground">{children}</div>
      {action}
    </div>
  )
}

function BackToAnalyses({ customerId }: { customerId: string }) {
  return (
    <Button asChild variant="outline">
      <Link href={analysesHref(customerId)}>Naar de analyses</Link>
    </Button>
  )
}

/** Verbruik van de brief, in de stijl van de regel onder de analyse. */
function UsageLine({ brief }: { brief: ContentBrief }) {
  const active = isBriefActive(brief.status)
  const usage = brief.ai_usage
  const claude =
    usage && usage.calls > 0
      ? `Claude ${formatUsd(usage.cost_usd)} in ${usage.calls} ${usage.calls === 1 ? "aanroep" : "aanroepen"}`
      : active
        ? "Claude nog niet gebruikt"
        : "Claude niet gebruikt"
  return (
    <p className="text-xs text-muted-foreground">
      Verbruik{active ? " tot nu toe" : ""}: {claude}
    </p>
  )
}

function WorkflowBar() {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-xl border bg-muted/50 px-5 py-3 text-[13px]">
      <Pill tone="blue">Workflow</Pill>
      <span className="min-w-0">
        Concept → review door SEO-specialist → akkoord. Er wordt nooit automatisch gepubliceerd.
      </span>
    </div>
  )
}

// --- Hoofdcomponent -------------------------------------------------------------------------

/**
 * Content brief en concepttekst voor één zoekwoord van een analyse (Figma 04, node 1:182).
 *
 * - Bij het openen worden de analyse (voor het zoekwoord en de kruimel) en de brief opgehaald.
 *   Geen brief (404) → lege staat met "Content brief maken".
 * - Zolang de brief loopt (`pending`/`brief`/`concept`) wordt hij elke 3 seconden ververst; de
 *   brief staat er al zodra die stap klaar is, ook als de concepttekst nog loopt.
 * - "Opnieuw genereren" schrijft alleen de tekst opnieuw; de vorige tekst blijft gedimd staan.
 */
export function ContentBriefView({ customerId, customerName, analysisId, keywordId }: ContentBriefViewProps) {
  const [analysis, setAnalysis] = useState<AnalysisDetail | null>(null)
  const [analysisError, setAnalysisError] = useState<LoadError | null>(null)
  const [brief, setBrief] = useState<ContentBrief | null>(null)
  const [briefError, setBriefError] = useState<LoadError | null>(null)
  const [briefLoaded, setBriefLoaded] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const [starting, setStarting] = useState(false)
  const [regenerating, setRegenerating] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [copyError, setCopyError] = useState<string | null>(null)
  const copyRef = useRef<HTMLDivElement>(null)

  // Analyse en brief ophalen bij het openen (en bij "Opnieuw proberen").
  useEffect(() => {
    if (!keywordId) return
    let ignore = false
    fetchAnalysis(analysisId)
      .then((next) => {
        if (ignore) return
        setAnalysis(next)
        setAnalysisError(null)
      })
      .catch((err: unknown) => {
        if (!ignore) setAnalysisError(toLoadError(err))
      })
    fetchBrief(analysisId, keywordId)
      .then((next) => {
        if (ignore) return
        setBrief(next)
        setBriefError(null)
        setBriefLoaded(true)
      })
      .catch((err: unknown) => {
        if (ignore) return
        setBriefError(toLoadError(err))
        setBriefLoaded(true)
      })
    return () => {
      ignore = true
    }
  }, [analysisId, keywordId, attempt])

  const active = brief !== null && isBriefActive(brief.status)

  const { failing } = usePolling(
    async () => {
      if (!keywordId) return
      setBrief(await fetchBrief(analysisId, keywordId))
    },
    active,
    POLL_INTERVAL_MS
  )

  async function start() {
    if (!keywordId) return
    setStarting(true)
    setActionError(null)
    try {
      setBrief(await startBrief(analysisId, keywordId))
      setBriefError(null)
    } catch (err) {
      if (err instanceof CompetitorAnalysisError && err.status === 409) {
        // Bestaat al of loopt al: de actuele stand tonen.
        const latest = await fetchBrief(analysisId, keywordId).catch(() => null)
        if (latest) {
          setBrief(latest)
          setBriefError(null)
        }
      } else {
        setActionError(errorMessage(err))
      }
    } finally {
      setStarting(false)
    }
  }

  async function regenerate() {
    if (!keywordId) return
    setRegenerating(true)
    setActionError(null)
    try {
      setBrief(await regenerateConcept(analysisId, keywordId))
    } catch (err) {
      setActionError(errorMessage(err))
      const latest = await fetchBrief(analysisId, keywordId).catch(() => null)
      if (latest) setBrief(latest)
    } finally {
      setRegenerating(false)
    }
  }

  async function copyText() {
    const concept = brief?.concept
    if (!concept) return
    setCopyError(null)
    const text = conceptMarkdown(concept)
    try {
      const html = copyRef.current?.innerHTML
      if (html && typeof ClipboardItem !== "undefined") {
        await navigator.clipboard.write([
          new ClipboardItem({
            "text/html": new Blob([html], { type: "text/html" }),
            "text/plain": new Blob([text], { type: "text/plain" }),
          }),
        ])
      } else {
        await navigator.clipboard.writeText(text)
      }
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      setCopyError("Kopiëren naar het klembord is mislukt.")
    }
  }

  const keyword = analysis?.keywords.find((item) => item.id === keywordId) ?? null
  const keywordText = brief?.keyword ?? keyword?.keyword ?? null

  const breadcrumb = (
    <Breadcrumb
      customerId={customerId}
      customerName={customerName}
      analysisId={analysisId}
      keywordId={keywordId}
      keyword={keywordText}
    />
  )

  // --- Geen zoekwoord, onbekende analyse of zoekwoord, laadfout ---

  if (!keywordId) {
    return (
      <div className="space-y-6">
        {breadcrumb}
        <Notice title="Geen zoekwoord gekozen" action={<BackToAnalyses customerId={customerId} />}>
          Open de content brief vanuit het resultaat van een analyse, via de knop “Content brief maken”.
        </Notice>
      </div>
    )
  }

  if (analysisError?.status === 404 || (analysis && briefLoaded && !keyword && !brief)) {
    return (
      <div className="space-y-6">
        {breadcrumb}
        <Notice
          title={analysisError ? "Analyse niet gevonden" : "Zoekwoord niet gevonden"}
          action={<BackToAnalyses customerId={customerId} />}
        >
          {analysisError
            ? "Deze analyse bestaat niet (meer) of hoort bij een andere klant."
            : "Dit zoekwoord hoort niet bij deze analyse."}
        </Notice>
      </div>
    )
  }

  const briefMissing = briefError?.status === 404
  const loadFailed = (briefError && !briefMissing) || (analysisError && !brief)

  if (loadFailed) {
    return (
      <div className="space-y-6">
        {breadcrumb}
        <Notice
          action={
            <Button variant="outline" onClick={() => setAttempt((value) => value + 1)}>
              <RotateCcw />
              Opnieuw proberen
            </Button>
          }
        >
          De content brief kon niet worden opgehaald: {(briefError && !briefMissing ? briefError : analysisError)?.message}
        </Notice>
      </div>
    )
  }

  if (!briefLoaded || (briefMissing && !analysis)) {
    return (
      <div className="space-y-6" aria-busy="true">
        {breadcrumb}
        <p role="status" className="sr-only">
          Content brief laden…
        </p>
        <div className="space-y-3">
          <Skeleton className="h-9 w-80 max-w-full" />
          <Skeleton className="h-4 w-96 max-w-full" />
        </div>
        <div className="grid items-start gap-6 lg:grid-cols-[420px_minmax(0,1fr)]">
          <Skeleton className="h-96 w-full rounded-xl" />
          <Skeleton className="h-96 w-full rounded-xl" />
        </div>
      </div>
    )
  }

  const title = (
    <h1 className="text-2xl font-bold tracking-tight break-words sm:text-[28px]">
      Brief & concept{keywordText ? `: “${keywordText}”` : ""}
    </h1>
  )

  // --- Nog geen brief ---

  if (!brief) {
    const keywordReady = keyword?.status === "completed"
    return (
      <div className="space-y-6">
        <header className="space-y-2">
          {breadcrumb}
          {title}
        </header>
        {actionError && <ErrorBlock>{actionError}</ErrorBlock>}
        <Notice
          title="Nog geen content brief"
          action={
            // Een uitgeschakelde knop krijgt geen muisgebeurtenissen; de uitleg staat op de omhulling.
            <span title={keywordReady ? undefined : NOT_READY_TEXT}>
              <Button onClick={start} disabled={!keywordReady || starting}>
                {starting ? <Loader2 className="animate-spin" aria-hidden="true" /> : <FileText aria-hidden="true" />}
                Content brief maken
              </Button>
            </span>
          }
        >
          Claude stelt op basis van deze analyse een content brief op (doel, title en meta, structuur en randvoorwaarden)
          en schrijft daarna een concepttekst om te reviewen. Er wordt niets gepubliceerd.
          {!keywordReady && <span className="mt-2 block">{NOT_READY_TEXT}</span>}
        </Notice>
      </div>
    )
  }

  // --- Brief (lopend, mislukt of klaar) ---

  const analysisDate = formatShortDate(brief.analysis_date)
  const meta = [
    analysisDate ? `Gebaseerd op analyse van ${analysisDate}` : "Gebaseerd op de concurrentieanalyse",
    `doelpagina ${brief.target_url ? targetPath(brief.target_url) : "nieuwe pagina"}`,
    `status: ${STATUS_TEXT[brief.status] ?? brief.status}`,
  ]
  const failed = brief.status === "failed"
  const concept = brief.concept

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0 space-y-2">
          {breadcrumb}
          {title}
          <p className="flex flex-wrap gap-x-1.5 text-[13px] text-muted-foreground">
            {meta.map((part, index) => (
              <span key={index} className="inline-flex gap-x-1.5" title={index === 1 ? (brief.target_url ?? undefined) : undefined}>
                {index > 0 && <span aria-hidden="true">·</span>}
                {part}
              </span>
            ))}
          </p>
        </div>
        {concept && (
          <Button variant="outline" onClick={copyText} className="shrink-0">
            {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
            {copied ? "Gekopieerd" : "Kopieer tekst"}
          </Button>
        )}
      </header>

      {active && (
        <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" aria-hidden="true" />
          {runningLabel(brief)}
        </p>
      )}
      <PollingFailedNotice failing={failing} />
      {actionError && <ErrorBlock>{actionError}</ErrorBlock>}
      {copyError && <ErrorBlock>{copyError}</ErrorBlock>}
      {failed && (
        <ErrorBlock
          action={
            <Button size="sm" variant="outline" onClick={start} disabled={starting}>
              {starting ? <Loader2 className="animate-spin" aria-hidden="true" /> : <RotateCcw aria-hidden="true" />}
              Opnieuw proberen
            </Button>
          }
        >
          Het maken van de content brief is mislukt: {brief.error_message?.trim() || "onbekende fout"}.
          {brief.brief ? " Wat wel klaar is, staat hieronder." : ""}
        </ErrorBlock>
      )}

      <div className="grid items-start gap-6 lg:grid-cols-[420px_minmax(0,1fr)]">
        {brief.brief ? (
          <BriefCard brief={brief.brief} customerId={customerId} />
        ) : (
          <ResultCard id="content-brief" title="Content brief" description="Automatisch opgesteld uit de concurrentieanalyse.">
            {active ? (
              <p role="status" className="flex items-center gap-2 rounded-lg border border-dashed px-4 py-6 text-sm text-muted-foreground">
                <Loader2 className="size-4 shrink-0 animate-spin" aria-hidden="true" />
                Brief wordt opgesteld…
              </p>
            ) : (
              <p className="rounded-lg border border-dashed px-4 py-5 text-sm text-muted-foreground">
                De brief kon niet worden opgesteld.
              </p>
            )}
          </ResultCard>
        )}

        <ConceptCard
          concept={concept}
          model={brief.model}
          running={active}
          runningLabel={brief.brief ? "Concepttekst wordt geschreven…" : "De tekst wordt geschreven zodra de brief klaar is…"}
          failed={failed}
          errorMessage={failed ? brief.error_message : null}
          regenerating={regenerating}
          onRegenerate={regenerate}
        />
      </div>

      <WorkflowBar />
      <UsageLine brief={brief} />

      {/* Bron voor "Kopieer tekst": de volledige tekst met echte kopniveaus, zonder review-meldingen. */}
      {concept && (
        <div ref={copyRef} hidden>
          <ConceptCopyText concept={concept} />
        </div>
      )}
    </div>
  )
}
