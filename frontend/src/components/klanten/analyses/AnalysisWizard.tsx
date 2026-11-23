"use client"

import { useMemo, useState } from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { Check, Loader2, RefreshCw } from "lucide-react"

import { EstimateBar } from "@/components/klanten/analyses/EstimateBar"
import { KeywordRows } from "@/components/klanten/analyses/KeywordRows"
import { SourcesCard } from "@/components/klanten/analyses/SourcesCard"
import { WizardModulesCard, WizardSettingsCard } from "@/components/klanten/analyses/WizardSettings"
import {
  createRow,
  CUSTOM_URL,
  hostOf,
  keywordKey,
  knownByKey,
  rowTargetUrl,
  toKeywordInputs,
  validate,
  type WizardRow,
} from "@/components/klanten/analyses/wizard-model"
import { useRequest } from "@/components/analytics/compare/use-request"
import { ErrorNote, Notice } from "@/components/analytics/states"
import { Button } from "@/components/ui/button"
import { customerHref } from "@/lib/active-customer"
import {
  analysesHref,
  analysisHref,
  CompetitorAnalysisError,
  estimate,
  fetchProposal,
  startAnalysis,
  type Module,
  type ProposalResponse,
  type TopN,
} from "@/lib/competitor-analysis"
import { cn } from "@/lib/utils"

export type AnalysisWizardProps = {
  customerId: string
  customerName: string
  /** Domein van de klant zonder protocol, bijv. "iexist.nl". */
  customerDomain: string
  /** Volledige URL van de klantsite, bijv. "https://www.iexist.nl". */
  customerBaseUrl: string
  /** Zoekwoorden uit `?zoekwoord=` (herhaalbaar), getrimd en ontdubbeld; leeg = niets ingevuld. */
  initialKeywords: string[]
}

// Wizard "Nieuwe analyse" (Figma 02, node 1:98): één pagina met zoekwoorden en doelpagina's,
// instellingen, modules, databronnen en een schattingsbalk met "Start analyse".
export function AnalysisWizard(props: AnalysisWizardProps) {
  const { customerId, customerName } = props
  const [attempt, setAttempt] = useState(0)
  const proposal = useRequest<ProposalResponse>(`${customerId}:${attempt}`, () => fetchProposal(customerId))

  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <nav aria-label="Kruimelpad">
          <ol className="flex flex-wrap items-center gap-1.5 text-sm text-muted-foreground">
            <li>
              <Link href={customerHref("home", customerId)} className="hover:text-foreground hover:underline">
                {customerName}
              </Link>
            </li>
            <li aria-hidden>/</li>
            <li>
              <Link href={analysesHref(customerId)} className="hover:text-foreground hover:underline">
                Concurrentieanalyse
              </Link>
            </li>
            <li aria-hidden>/</li>
            <li aria-current="page" className="text-foreground">
              Nieuwe analyse
            </li>
          </ol>
        </nav>
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Nieuwe concurrentieanalyse</h1>
        <p className="text-sm text-muted-foreground">
          Kies zoekwoorden, de doelpagina per zoekwoord en wat er geanalyseerd moet worden.
        </p>
      </header>

      {proposal.data ? (
        <WizardForm key={customerId} proposal={proposal.data} {...props} />
      ) : proposal.error ? (
        <div className="space-y-3">
          <ErrorNote>Het voorstel kon niet worden geladen: {proposal.error}</ErrorNote>
          <Button type="button" variant="outline" size="sm" onClick={() => setAttempt((value) => value + 1)}>
            <RefreshCw />
            Opnieuw proberen
          </Button>
        </div>
      ) : (
        <div
          role="status"
          className="flex items-center gap-3 rounded-xl border bg-card px-6 py-10 text-sm text-muted-foreground"
        >
          <Loader2 className="size-4 animate-spin" aria-hidden />
          Zoekwoorden en databronnen ophalen… Dit kan tot een halve minuut duren.
        </div>
      )}
    </div>
  )
}

type SubmitError = { message: string; status: number }

function WizardForm({
  proposal,
  customerId,
  customerDomain,
  customerBaseUrl,
  initialKeywords,
}: AnalysisWizardProps & { proposal: ProposalResponse }) {
  const router = useRouter()
  const { sources, defaults, rates } = proposal
  const maxKeywords = Math.max(1, proposal.max_keywords)
  const known = useMemo(() => knownByKey(proposal.keywords), [proposal.keywords])

  const host = hostOf(customerBaseUrl) || hostOf(customerDomain)
  const baseUrl = customerBaseUrl.trim() || (host ? `https://${customerDomain.trim()}` : "")

  const [rows, setRows] = useState<WizardRow[]>(() => {
    const initial = initialKeywords.slice(0, maxKeywords).map((keyword) => createRow(keyword, known))
    return initial.length > 0 ? initial : [createRow("", known)]
  })
  const [country, setCountry] = useState(defaults.country)
  const [topN, setTopN] = useState<TopN>(defaults.top_n)
  const [excludeAggregators, setExcludeAggregators] = useState(defaults.exclude_aggregators)
  const [modules, setModules] = useState<Module[]>(defaults.modules)
  const [showErrors, setShowErrors] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<SubmitError | null>(null)

  const ahrefsBlocked = sources.ahrefs.state === "not_configured"
  const aiConfigured = sources.claude.state === "ok"
  const droppedKeywords = Math.max(0, initialKeywords.length - maxKeywords)

  const validation = validate({ rows, modules, maxKeywords, host, baseUrl })
  const filledRows = rows.filter((row) => keywordKey(row.keyword))
  const keywordCount = new Set(filledRows.map((row) => keywordKey(row.keyword))).size
  const ownUrls = filledRows.filter((row) => rowTargetUrl(row, baseUrl) !== null).length
  const plan = estimate(rates, { keywords: keywordCount, topN, ownUrls, modules, aiConfigured })

  const keywordsReady = keywordCount > 0 && Object.keys(validation.rows).length === 0 && !validation.keywords
  const steps = [
    { label: "Zoekwoorden", done: keywordsReady },
    { label: "Instellingen", done: modules.length > 0 },
    { label: "Bronnen", done: !ahrefsBlocked },
    { label: "Starten", done: false },
  ]

  /** Zet de focus op het eerste veld met een melding. */
  function focusFirstError() {
    for (const row of rows) {
      const errors = validation.rows[row.id]
      if (errors?.keyword) return document.getElementById(`wizard-kw-${row.id}`)?.focus()
      if (errors?.url && row.target === CUSTOM_URL) return document.getElementById(`wizard-url-${row.id}`)?.focus()
    }
    if (validation.keywords) return document.getElementById(`wizard-kw-${rows[rows.length - 1]?.id}`)?.focus()
    if (validation.modules) document.getElementById("wizard-module-serp")?.focus()
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (ahrefsBlocked || submitting) return
    setShowErrors(true)
    setSubmitError(null)
    if (!validation.valid) {
      focusFirstError()
      return
    }
    setSubmitting(true)
    try {
      const analysis = await startAnalysis(customerId, {
        keywords: toKeywordInputs(rows, baseUrl),
        country,
        top_n: topN,
        exclude_aggregators: excludeAggregators,
        modules,
      })
      // De knop blijft in de laadtoestand tot de resultaatpagina er is.
      router.push(analysisHref(customerId, analysis.id))
    } catch (error) {
      setSubmitError(
        error instanceof CompetitorAnalysisError
          ? { message: error.message, status: error.status }
          : { message: "De analyse kon niet worden gestart.", status: 0 }
      )
      setSubmitting(false)
    }
  }

  return (
    <form noValidate onSubmit={submit} className="space-y-6">
      <nav aria-label="Voortgang">
        <ol className="flex flex-wrap items-center gap-x-4 gap-y-2">
          {steps.map((step, index) => (
            <li key={step.label} className="flex items-center gap-2 text-sm">
              <span
                aria-hidden
                className={cn(
                  "flex size-5 items-center justify-center rounded-full text-[11px] font-bold",
                  step.done ? "bg-green-600 text-white" : "bg-muted text-muted-foreground"
                )}
              >
                {step.done ? <Check className="size-3" strokeWidth={3} /> : index + 1}
              </span>
              <span className={step.done ? "font-medium" : "text-muted-foreground"}>{step.label}</span>
              <span className="sr-only">{step.done ? ": in orde" : ": nog niet in orde"}</span>
            </li>
          ))}
        </ol>
      </nav>

      {ahrefsBlocked && (
        <ErrorNote>
          Ahrefs is niet ingesteld, dus er kan geen analyse worden gestart.{" "}
          {sources.ahrefs.message ?? "Vul AHREFS_API_KEY in de backend-configuratie in."}
        </ErrorNote>
      )}
      {!ahrefsBlocked && sources.ahrefs.state !== "ok" && sources.ahrefs.message && (
        <Notice>{sources.ahrefs.message}</Notice>
      )}
      {!aiConfigured && (
        <Notice>
          Claude is niet ingesteld. De analyse kan wel starten; onderwerpdekking, E-E-A-T en verbeterpunten tonen dan
          &quot;niet ingesteld&quot;.
        </Notice>
      )}
      {droppedKeywords > 0 && (
        <Notice>
          Er waren {initialKeywords.length} zoekwoorden geselecteerd; per analyse kunnen er maximaal {maxKeywords}. De
          eerste {maxKeywords} staan hieronder.
        </Notice>
      )}

      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <KeywordRows
          rows={rows}
          onRowsChange={setRows}
          known={known}
          proposalKeywords={proposal.keywords}
          pages={proposal.pages}
          maxKeywords={maxKeywords}
          host={host}
          errors={validation.rows}
          formError={validation.keywords}
          showErrors={showErrors}
        />
        <div className="space-y-6">
          <WizardSettingsCard
            country={country}
            onCountryChange={setCountry}
            defaultCountry={defaults.country}
            topN={topN}
            onTopNChange={setTopN}
            excludeAggregators={excludeAggregators}
            onExcludeAggregatorsChange={setExcludeAggregators}
          />
          <WizardModulesCard modules={modules} onModulesChange={setModules} sources={sources} error={validation.modules} />
        </div>
      </div>

      <SourcesCard sources={sources} />

      {submitError && (
        <ErrorNote>
          {submitError.message}
          {submitError.status === 409 && (
            <>
              {" "}
              <Link href={analysesHref(customerId)} className="font-semibold underline underline-offset-2">
                Naar de analyses
              </Link>
            </>
          )}
        </ErrorNote>
      )}
      {showErrors && !validation.valid && !submitError && (
        <p role="alert" className="text-sm text-red-700 dark:text-red-300">
          Controleer de gemarkeerde velden voordat je de analyse start.
        </p>
      )}

      <EstimateBar
        keywords={keywordCount}
        topN={topN}
        estimate={plan}
        aiConfigured={aiConfigured}
        disabled={ahrefsBlocked}
        submitting={submitting}
      />
    </form>
  )
}
