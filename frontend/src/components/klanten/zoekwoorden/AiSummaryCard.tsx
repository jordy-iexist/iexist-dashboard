import { Sparkles } from "lucide-react"

import { CardMessage, ResultCard } from "@/components/klanten/analyses/result-parts"
import type { Summary } from "@/lib/keyword-competitors"

const MESSAGE_TEXTS = {
  empty: "Er is nog geen samenvatting. Die verschijnt na het ophalen van de concurrenten.",
  not_configured: "Claude is niet ingesteld, dus er is geen samenvatting geschreven.",
  unavailable: "De samenvatting kon niet worden geschreven.",
}

/** Kaart "Wat valt op (AI)": een alinea over de kansen en drie punten van Claude. */
export function AiSummaryCard({ summary }: { summary: Summary }) {
  const filled = summary.state === "ok" && (summary.paragraph || summary.points.length > 0)

  let content: React.ReactNode
  if (filled) {
    content = (
      <>
        {summary.paragraph && (
          <div className="rounded-lg bg-indigo-50 px-4 py-3 dark:bg-indigo-950/40">
            <p className="flex items-center gap-1.5 text-xs font-semibold text-indigo-900 dark:text-indigo-200">
              <Sparkles className="size-3.5" aria-hidden="true" />
              Kansen
            </p>
            <p className="mt-1.5 text-[13px] leading-relaxed text-indigo-950 dark:text-indigo-100">
              {summary.paragraph}
            </p>
          </div>
        )}
        {summary.points.length > 0 && (
          <ul className="space-y-2.5 text-[13px] leading-relaxed">
            {summary.points.map((point, index) => (
              <li key={index} className="flex gap-2">
                <span aria-hidden="true" className="shrink-0 font-semibold text-muted-foreground">
                  →
                </span>
                <span className="min-w-0">{point}</span>
              </li>
            ))}
          </ul>
        )}
      </>
    )
  } else {
    // skipped (bijv. te weinig cijfers) en een lege samenvatting tonen we als "Geen gegevens".
    const state =
      summary.state === "not_configured" ? "not_configured" : summary.state === "error" ? "unavailable" : "empty"
    content = (
      <CardMessage
        state={state}
        texts={{ ...MESSAGE_TEXTS, ...(summary.message ? { [state]: summary.message } : {}) }}
        error={summary.message}
      />
    )
  }

  return (
    <ResultCard id="wat-valt-op" title="Wat valt op (AI)">
      {content}
    </ResultCard>
  )
}
