"use client"

import { useState } from "react"
import ReactMarkdown from "react-markdown"
import { Loader2, MessageSquare, RefreshCw } from "lucide-react"

import { CardMessage, formatInt } from "@/components/klanten/analyses/result-parts"
import { Pill } from "@/components/livegang/shared"
import { Button } from "@/components/ui/button"
import { modelLabel, type Concept, type ConceptSection, type HeadingLevel } from "@/lib/content-brief"
import { cn } from "@/lib/utils"

/** Zoveel secties staan standaard open (ongeveer wat het ontwerp laat zien). */
const VISIBLE_SECTIONS = 3

/**
 * Koppen in het scherm: één niveau onder de kaarttitel (h2), zodat de pagina-h1 de enige h1 is.
 * De kopie naar het klembord gebruikt wel de echte niveaus (`ConceptCopyText`).
 */
const SCREEN_HEADINGS: Record<HeadingLevel, { tag: "h3" | "h4" | "h5"; className: string }> = {
  h1: { tag: "h3", className: "text-[28px] leading-tight font-bold tracking-tight" },
  h2: { tag: "h4", className: "text-xl leading-snug font-semibold" },
  h3: { tag: "h5", className: "text-base leading-snug font-semibold" },
}

const BODY_CLASS =
  "prose max-w-none text-[15px] leading-6 [overflow-wrap:anywhere] dark:prose-invert prose-p:my-3 prose-li:my-1"

function SectionView({ section }: { section: ConceptSection }) {
  const heading = SCREEN_HEADINGS[section.level] ?? SCREEN_HEADINGS.h2
  const Heading = heading.tag
  const body = section.body.trim()
  const note = section.review_note?.trim()

  return (
    <div className="space-y-3">
      <Heading className={cn("break-words", heading.className)}>{section.heading}</Heading>
      {note ? (
        <div className="space-y-2 rounded-lg bg-amber-50 px-4 py-3 dark:bg-amber-900/20">
          {body && (
            <div className={BODY_CLASS}>
              <ReactMarkdown>{body}</ReactMarkdown>
            </div>
          )}
          <p className="flex items-start gap-1.5 text-xs text-amber-800 dark:text-amber-300">
            <MessageSquare className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
            <span>Review: {note}</span>
          </p>
        </div>
      ) : (
        body && (
          <div className={BODY_CLASS}>
            <ReactMarkdown>{body}</ReactMarkdown>
          </div>
        )
      )}
    </div>
  )
}

/** De volledige tekst met echte kopniveaus en zonder review-meldingen, om te kopiëren. */
export function ConceptCopyText({ concept }: { concept: Concept }) {
  return (
    <>
      {concept.sections.map((section, index) => {
        const Heading = section.level
        return (
          <div key={index}>
            <Heading>{section.heading}</Heading>
            {section.body.trim() && <ReactMarkdown>{section.body.trim()}</ReactMarkdown>}
          </div>
        )
      })}
    </>
  )
}

/** Platte tekst (Markdown) van het concept, zonder review-meldingen. */
export function conceptMarkdown(concept: Concept) {
  return concept.sections
    .map((section) => {
      const hashes = "#".repeat(Number(section.level.slice(1)) || 2)
      const body = section.body.trim()
      return body ? `${hashes} ${section.heading}\n\n${body}` : `${hashes} ${section.heading}`
    })
    .join("\n\n")
}

export type ConceptCardProps = {
  concept: Concept | null
  model: string | null
  /** Er loopt een run (brief of concept). */
  running: boolean
  /** Tekst bij een lopende run zonder concept, bijv. "Concepttekst wordt geschreven…". */
  runningLabel: string
  /** De run is mislukt; de melding staat bovenaan de pagina. */
  failed: boolean
  errorMessage: string | null
  /** De knop "Opnieuw genereren" is net ingedrukt en de aanvraag loopt. */
  regenerating: boolean
  onRegenerate: () => void
}

/** De rechterkaart: concepttekst met controles (Figma 04, node 1:182). */
export function ConceptCard({
  concept,
  model,
  running,
  runningLabel,
  failed,
  errorMessage,
  regenerating,
  onRegenerate,
}: ConceptCardProps) {
  const [expanded, setExpanded] = useState(false)
  const sections = concept?.sections ?? []
  const hiddenCount = Math.max(0, sections.length - VISIBLE_SECTIONS)
  const shown = expanded ? sections : sections.slice(0, VISIBLE_SECTIONS)
  // Tijdens een nieuwe run blijft de vorige tekst staan tot de nieuwe er is.
  const stale = running && concept !== null

  return (
    <section aria-labelledby="concept-title" className="flex min-w-0 flex-col overflow-hidden rounded-xl border bg-card">
      <h2 id="concept-title" className="sr-only">
        Concepttekst
      </h2>

      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b bg-muted/50 px-6 py-3">
        <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
          <Pill tone="blue">{concept ? `AI-concept v${concept.version}` : "AI-concept"}</Pill>
          <span className="text-[13px] text-muted-foreground">
            {modelLabel(model)}
            {concept && ` · ${formatInt(concept.word_count)} woorden`}
          </span>
        </div>
        {concept && (
          // Een uitgeschakelde knop krijgt geen muisgebeurtenissen; de uitleg staat op de omhulling.
          <span title={running ? "Er wordt al een tekst geschreven; wacht tot die klaar is." : undefined}>
            <Button size="sm" variant="outline" onClick={onRegenerate} disabled={running || regenerating}>
              {regenerating ? <Loader2 className="animate-spin" aria-hidden="true" /> : <RefreshCw aria-hidden="true" />}
              Opnieuw genereren
            </Button>
          </span>
        )}
      </div>

      {concept && concept.checks.length > 0 && (
        <ul aria-label="Controles" className="flex flex-wrap gap-1.5 border-b px-6 py-3">
          {concept.checks.map((check) => (
            <li key={check.key}>
              <Pill tone={check.ok ? "green" : "amber"}>
                <span aria-hidden="true">{check.ok ? "✓" : "!"}</span>
                {check.label}
                <span className="sr-only">{check.ok ? " (in orde)" : " (controleren)"}</span>
              </Pill>
            </li>
          ))}
        </ul>
      )}

      {concept ? (
        <div className="space-y-6 px-6 pt-8 pb-6 sm:px-12">
          {stale && (
            <p
              role="status"
              className="flex items-start gap-2 rounded-md border border-dashed px-3 py-2 text-sm text-muted-foreground"
            >
              <Loader2 className="mt-0.5 size-4 shrink-0 animate-spin" aria-hidden="true" />
              <span>
                Er wordt een nieuwe versie geschreven. Hieronder staat nog versie {concept.version}.
              </span>
            </p>
          )}

          <article
            aria-label="Concepttekst"
            className={cn("space-y-6 transition-opacity", stale && "opacity-60")}
          >
            {shown.map((section, index) => (
              <SectionView key={index} section={section} />
            ))}
          </article>

          {hiddenCount > 0 && (
            <p className="text-center text-sm">
              <button
                type="button"
                onClick={() => setExpanded((value) => !value)}
                aria-expanded={expanded}
                className="font-medium text-blue-700 underline-offset-2 hover:underline dark:text-blue-400"
              >
                {expanded
                  ? "Toon minder"
                  : `… nog ${hiddenCount} ${hiddenCount === 1 ? "sectie" : "secties"} · Toon volledige tekst`}
              </button>
            </p>
          )}
        </div>
      ) : (
        <div className="px-6 py-5">
          {running ? (
            <CardMessage state="pending" texts={{ pending: runningLabel }} />
          ) : (
            <CardMessage
              state={failed ? "unavailable" : "empty"}
              error={errorMessage}
              texts={{
                unavailable: "De concepttekst kon niet worden geschreven.",
                empty: "Er is nog geen concepttekst.",
              }}
            />
          )}
        </div>
      )}
    </section>
  )
}
