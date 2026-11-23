import { CircleHelp } from "lucide-react"

import { CardMessage, ResultCard, type ResultCardState } from "@/components/klanten/analyses/result-parts"
import { MISSING_TOPIC_KIND_LABELS, type MissingTopic } from "@/lib/competitor-analysis"

/** Onderwerpen en vragen die concurrenten behandelen en de eigen pagina niet (AI-analyse). */
export function MissingTopicsCard({
  topics,
  state,
  error,
  hasOwnPage,
}: {
  topics: MissingTopic[]
  state: ResultCardState
  error?: string | null
  /** Zonder eigen pagina gaat het om onderwerpen die een nieuwe pagina moet behandelen. */
  hasOwnPage: boolean
}) {
  return (
    <ResultCard
      id="missing-topics"
      title="Ontbrekende onderwerpen"
      description={
        hasOwnPage
          ? "Behandeld door concurrenten, niet op jouw pagina (AI-analyse)."
          : "Behandeld door concurrenten; om mee te nemen in een nieuwe pagina (AI-analyse)."
      }
    >
      {state !== "filled" ? (
        <CardMessage
          state={state}
          error={error}
          texts={{
            pending: "De onderwerpen worden vergeleken zodra de pagina's zijn opgehaald…",
            empty: "Er zijn geen onderwerpen gevonden die concurrenten wel en jouw pagina niet behandelt.",
            not_configured: "Er is geen Claude-sleutel ingesteld (ANTHROPIC_API_KEY), dus de onderwerpdekking is niet geanalyseerd.",
            unavailable: "De AI-analyse van de onderwerpen is mislukt.",
          }}
        />
      ) : (
        <ul className="divide-y text-sm">
          {topics.map((topic) => (
            <li key={`${topic.kind}-${topic.topic}`} className="flex items-start gap-3 py-2 first:pt-0 last:pb-0">
              <span className="flex min-w-0 flex-1 items-start gap-1.5">
                {topic.kind === "question" && (
                  <CircleHelp className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
                )}
                <span className="min-w-0">
                  {topic.kind === "question" && <span className="sr-only">{MISSING_TOPIC_KIND_LABELS.question}: </span>}
                  {topic.topic}
                </span>
              </span>
              <span
                className="shrink-0 text-xs tabular-nums text-muted-foreground"
                title={`Behandeld door ${topic.covered} van de ${topic.total} meegetelde concurrenten`}
              >
                {topic.covered}/{topic.total}
                <span className="sr-only"> concurrenten</span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </ResultCard>
  )
}
