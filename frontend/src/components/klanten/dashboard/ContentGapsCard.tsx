import type { CustomerRankings } from "@/lib/customer-types"

function emptyText(rankings: CustomerRankings) {
  if (rankings.state === "ok") {
    return "Geen gevolgde zoekwoorden met volume zonder ranking."
  }
  if (rankings.state === "not_tracked") {
    return "Deze website wordt niet gevolgd in Pro Rank Tracker."
  }
  return (
    rankings.message ||
    (rankings.state === "not_configured"
      ? "De koppeling met Pro Rank Tracker is niet ingesteld."
      : "De zoekwoorden uit Pro Rank Tracker konden niet worden opgehaald.")
  )
}

// Gevolgde zoekwoorden met volume waarvoor de klant niet in de top 100 staat.
export function ContentGapsCard({
  rankings,
  customerName,
}: {
  rankings: CustomerRankings
  customerName: string
}) {
  const gaps = rankings.state === "ok" ? rankings.content_gaps : []
  const more = rankings.state === "ok" ? rankings.content_gaps_total - gaps.length : 0

  return (
    <section
      aria-labelledby="content-gaps-title"
      className="flex flex-col gap-4 rounded-xl border bg-card px-6 py-5"
    >
      <div className="space-y-1">
        <h2 id="content-gaps-title" className="text-base font-semibold">
          Contentkansen – nog geen ranking
        </h2>
        <p className="text-[13px] text-muted-foreground">
          Gevolgde zoekwoorden met volume waarvoor geen pagina van {customerName} in de top 100
          staat. Bron: Pro Rank Tracker.
        </p>
      </div>

      {gaps.length === 0 ? (
        <p className="rounded-lg border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
          {emptyText(rankings)}
        </p>
      ) : (
        <ul>
          {gaps.map((gap) => (
            <li key={gap.keyword} className="flex items-center gap-3 border-b py-2.5">
              <div className="min-w-0 flex-1 space-y-0.5">
                <p className="text-sm font-semibold break-words">{gap.keyword}</p>
                <p className="text-xs text-muted-foreground">
                  {gap.volume.toLocaleString("nl-NL")} /mnd
                </p>
              </div>
              <span
                aria-disabled="true"
                title="Binnenkort"
                className="cursor-not-allowed text-[13px] font-semibold whitespace-nowrap text-muted-foreground"
              >
                Brief maken →
              </span>
            </li>
          ))}
        </ul>
      )}

      {more > 0 && (
        <p className="text-xs text-muted-foreground">
          En nog {more.toLocaleString("nl-NL")} {more === 1 ? "zoekwoord" : "zoekwoorden"} zonder
          ranking.
        </p>
      )}
    </section>
  )
}
