import { CardMessage, ResultCard, type ResultCardState } from "@/components/klanten/analyses/result-parts"

/** Vragen uit "Mensen vragen ook" op de zoekresultatenpagina. */
export function PaaCard({ questions, state }: { questions: string[]; state: ResultCardState }) {
  return (
    <ResultCard id="paa" title="Vragen uit ‘Mensen vragen ook’">
      {state !== "filled" ? (
        <CardMessage
          state={state}
          texts={{
            pending: "De zoekresultaten worden nog opgehaald…",
            empty: "Google toont bij dit zoekwoord geen ‘Mensen vragen ook’.",
            not_configured: "De bron voor de zoekresultaten is niet ingesteld.",
            unavailable: "De vragen konden niet worden opgehaald.",
          }}
        />
      ) : (
        <ul className="list-disc space-y-1.5 pl-5 text-sm marker:text-muted-foreground">
          {questions.map((question) => (
            <li key={question}>{question}</li>
          ))}
        </ul>
      )}
    </ResultCard>
  )
}
