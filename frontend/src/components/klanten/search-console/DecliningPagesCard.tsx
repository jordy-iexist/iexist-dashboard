import { formatInt, ResultCard } from "@/components/klanten/analyses/result-parts"
import { urlPath } from "@/components/klanten/search-console/format"
import type { DecliningRow, DecliningSection } from "@/lib/search-console-insights"

const emptyClass =
  "rounded-lg border border-dashed px-4 py-6 text-center text-sm text-muted-foreground"

/**
 * Daling in procenten, berekend uit de klikken zelf (zo maakt het niet uit of de backend
 * `pct` als fractie of als percentage levert); null als er geen vorige klikken zijn.
 */
function dropPercent(row: DecliningRow): number | null {
  if (row.clicks_prev <= 0) return null
  return Math.round(((row.clicks - row.clicks_prev) / row.clicks_prev) * 100)
}

// Pagina's met de grootste daling in klikken t.o.v. de vorige periode, met mogelijke oorzaak.
export function DecliningPagesCard({ section }: { section: DecliningSection }) {
  const more = section.total - section.rows.length

  return (
    <ResultCard
      id="dalende-paginas"
      title="Dalende pagina's"
      description="Grootste daling in klikken t.o.v. vorige periode, met mogelijke oorzaak."
    >
      {section.state === "unavailable" ? (
        <p className={emptyClass}>
          {section.message || "De pagina's konden niet worden opgehaald uit Search Console."}
        </p>
      ) : section.rows.length === 0 ? (
        <p className={emptyClass}>Geen pagina&apos;s met een duidelijke daling in klikken.</p>
      ) : (
        <ul>
          {section.rows.map((row) => {
            const pct = dropPercent(row)
            return (
              <li key={row.page} className="flex items-start gap-3 border-b py-2.5">
                <div className="min-w-0 flex-1 space-y-0.5">
                  <a
                    href={row.page}
                    target="_blank"
                    rel="noreferrer noopener"
                    title={row.page}
                    className="block truncate text-sm font-semibold underline-offset-2 hover:underline"
                  >
                    {urlPath(row.page)}
                  </a>
                  {row.cause && <p className="text-xs text-muted-foreground">{row.cause}</p>}
                </div>
                <span
                  className="text-[13px] font-semibold whitespace-nowrap text-red-700 tabular-nums dark:text-red-400"
                  title={`${formatInt(row.clicks_prev)} → ${formatInt(row.clicks)} klikken`}
                >
                  {pct == null
                    ? `−${formatInt(Math.abs(row.delta))} klikken`
                    : `−${formatInt(Math.abs(pct))}% klikken`}
                </span>
              </li>
            )
          })}
        </ul>
      )}

      {section.state === "ok" && more > 0 && (
        <p className="text-xs text-muted-foreground">
          En nog {formatInt(more)} {more === 1 ? "pagina" : "pagina's"} met een daling.
        </p>
      )}
    </ResultCard>
  )
}
