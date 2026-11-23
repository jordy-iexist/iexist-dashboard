import { PageLink } from "@/components/livegang/comparison-parts"
import { CardMessage, ResultCard, YesNo, shortUrl, type ResultCardState } from "@/components/klanten/analyses/result-parts"
import type { Eeat, PageRow } from "@/lib/competitor-analysis"
import { cn } from "@/lib/utils"

const SIGNALS: { key: keyof Omit<Eeat, "note">; label: string }[] = [
  { key: "team", label: "Team" },
  { key: "cases", label: "Cases" },
  { key: "reviews", label: "Reviews" },
  { key: "certifications", label: "Certificeringen" },
]

const th = "px-3 py-2 text-left font-medium whitespace-nowrap"
const td = "px-3 py-2 align-top"

/** E-E-A-T-signalen per pagina; de eigen pagina bovenaan en gemarkeerd. */
export function EeatCard({
  pages,
  own,
  state,
  error,
}: {
  pages: PageRow[]
  own: PageRow | null
  state: ResultCardState
  error?: string | null
}) {
  const rows = [
    ...(own?.eeat ? [{ page: own, isOwn: true }] : []),
    ...pages.filter((page) => page.eeat).map((page) => ({ page, isOwn: false })),
  ]

  return (
    <ResultCard
      id="eeat"
      title="E-E-A-T-signalen"
      description="Laten de pagina's zien wie erachter zit en waarom je ze kunt vertrouwen? Volgens de AI-analyse van de paginatekst."
    >
      {state !== "filled" ? (
        <CardMessage
          state={state}
          error={error}
          texts={{
            pending: "De signalen worden bepaald zodra de pagina's zijn opgehaald…",
            empty: "Er zijn geen E-E-A-T-signalen bepaald, bijvoorbeeld omdat geen enkele pagina kon worden uitgelezen.",
            not_configured: "Er is geen Claude-sleutel ingesteld (ANTHROPIC_API_KEY), dus de E-E-A-T-signalen zijn niet bepaald.",
            unavailable: "De AI-analyse van de E-E-A-T-signalen is mislukt.",
          }}
        />
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-sm">
            <caption className="sr-only">E-E-A-T-signalen per pagina</caption>
            <thead className="bg-muted/50 text-xs text-muted-foreground">
              <tr>
                <th scope="col" className={th}>
                  Pagina
                </th>
                {SIGNALS.map((signal) => (
                  <th key={signal.key} scope="col" className={cn(th, "text-center")}>
                    {signal.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y">
              {rows.map(({ page, isOwn }) => {
                const eeat = page.eeat as Eeat
                return (
                  <tr
                    key={page.id}
                    className={cn(
                      isOwn && "border-b-2 border-b-primary/40 bg-primary/5",
                      !isOwn && page.is_excluded && "bg-muted/30 text-muted-foreground"
                    )}
                  >
                    <th scope="row" className={cn(td, "max-w-80 min-w-48 text-left font-normal")}>
                      <span className="flex min-w-0 items-baseline gap-1">
                        {isOwn ? (
                          <span className="shrink-0 font-semibold">Jij:</span>
                        ) : (
                          page.position != null && <span className="shrink-0 text-xs text-muted-foreground">{page.position}.</span>
                        )}
                        <PageLink url={page.url} label={shortUrl(page.url)} />
                      </span>
                      {eeat.note && <span className="mt-0.5 block text-xs text-muted-foreground">{eeat.note}</span>}
                    </th>
                    {SIGNALS.map((signal) => (
                      <td key={signal.key} className={cn(td, "text-center")}>
                        <YesNo value={eeat[signal.key]} yes={`${signal.label}: ja`} no={`${signal.label}: nee`} />
                      </td>
                    ))}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </ResultCard>
  )
}
