import { CircleCheck, CircleX } from "lucide-react"

import { PageLink } from "@/components/livegang/comparison-parts"
import { CardMessage, ResultCard, bareDomain, type ResultCardState } from "@/components/klanten/analyses/result-parts"
import type { AiOverview } from "@/lib/competitor-analysis"
import { cn } from "@/lib/utils"

/** Of het eigen domein in de AI Overview wordt geciteerd. */
function OwnCitedLine({ ownCited, customerDomain }: { ownCited: boolean | null; customerDomain: string }) {
  if (ownCited === null) {
    return <p className="text-[13px] text-muted-foreground">Onbekend of {customerDomain} wordt geciteerd.</p>
  }
  const Icon = ownCited ? CircleCheck : CircleX
  return (
    <p
      className={cn(
        "flex items-center gap-1.5 rounded-md px-3 py-2 text-[13px] font-medium",
        ownCited
          ? "bg-green-50 text-green-800 dark:bg-green-900/20 dark:text-green-300"
          : "bg-red-50 text-red-800 dark:bg-red-900/20 dark:text-red-300"
      )}
    >
      <Icon className="size-4 shrink-0" aria-hidden="true" />
      {customerDomain} wordt {ownCited ? "wel" : "niet"} geciteerd
    </p>
  )
}

/** Welke bronnen Google in de AI Overview citeert, met het eigen domein erbij. */
export function AiOverviewCard({
  aiOverview,
  state,
  customerDomain,
}: {
  aiOverview: AiOverview | null
  state: ResultCardState
  customerDomain: string
}) {
  const own = bareDomain(customerDomain)
  // Google citeert soms meerdere pagina's van één site; toon elk domein één keer (de eerste URL).
  const seenDomains = new Set<string>()
  const sources = (aiOverview?.sources ?? []).filter((source) => {
    const domain = bareDomain(source.domain)
    if (seenDomains.has(domain)) return false
    seenDomains.add(domain)
    return true
  })
  // Wel een AI Overview, maar zonder herkenbare bronnen.
  const presentWithoutSources = aiOverview?.state === "ok" && sources.length === 0

  return (
    <ResultCard id="ai-overview" title="AI Overview" description="Welke bronnen citeert Google in het AI-antwoord?">
      {state !== "filled" && !presentWithoutSources ? (
        <CardMessage
          state={state}
          texts={{
            pending: "De zoekresultaten worden nog opgehaald…",
            empty: "Google toont bij dit zoekwoord geen AI Overview.",
            not_configured: "De bron voor de zoekresultaten is niet ingesteld.",
            unavailable: "De AI Overview kon niet worden opgehaald.",
          }}
        />
      ) : (
        <>
          <OwnCitedLine ownCited={aiOverview?.own_cited ?? null} customerDomain={customerDomain} />
          {presentWithoutSources ? (
            <p className="text-[13px] text-muted-foreground">Google toont een AI Overview, maar zonder herkenbare bronnen.</p>
          ) : (
            <ol className="space-y-1.5 text-sm">
              {sources.map((source, index) => {
                const isOwn = bareDomain(source.domain) === own
                return (
                  <li key={`${source.domain}-${source.url ?? index}`} className={cn("flex min-w-0 items-baseline gap-2", isOwn && "font-semibold")}>
                    <span className="w-5 shrink-0 text-right text-xs tabular-nums text-muted-foreground">{index + 1}.</span>
                    <span className="min-w-0">
                      {source.url ? <PageLink url={source.url} label={source.domain} /> : source.domain}
                      {isOwn && <span className="ml-1 text-xs font-normal text-muted-foreground">(jij)</span>}
                    </span>
                  </li>
                )
              })}
            </ol>
          )}
        </>
      )}
    </ResultCard>
  )
}
