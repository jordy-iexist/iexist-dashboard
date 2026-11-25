import Link from "next/link"
import { Info } from "lucide-react"

import { CardMessage, ResultCard } from "@/components/klanten/analyses/result-parts"
import { formatCount } from "@/components/klanten/zoekwoorden/CompetitorKpis"
import { customerHref } from "@/lib/active-customer"
import type { Heatmap, HeatmapCell, HeatmapColumn } from "@/lib/keyword-competitors"
import { cn } from "@/lib/utils"

/**
 * Tinten uit het ontwerp (0–9, 10–24, 25–49, ≥50 procent). Donkere tekst op 0–2, wit op 3.
 * In een donker thema wordt de lichtste tint een gedempt vlak, zodat die niet oplicht.
 */
const LEVEL_CLASSES = [
  "bg-[#f2f4f7] text-neutral-700 dark:bg-white/10 dark:text-white/70",
  "bg-[#e0e7ff] text-indigo-950",
  "bg-[#a5b4fc] text-indigo-950",
  "bg-[#6366f1] text-white",
] as const

const LEGEND = ["0–9%", "10–24%", "25–49%", "≥ 50%"]

/** Meerdelige landcodes waarbij ook het tweede deel van achteren ruis is (bijv. "co.uk"). */
const SECOND_LEVEL = new Set(["co", "com", "org", "net", "ac", "gov"])
const MAX_LABEL = 14

/** Domein zonder TLD en ingekort: "voorbeeld-installaties.nl" → "voorbeeld-inst…". */
function columnLabel(domain: string) {
  const parts = domain.replace(/^www\./, "").split(".")
  if (parts.length > 1) parts.pop()
  if (parts.length > 1 && SECOND_LEVEL.has(parts[parts.length - 1])) parts.pop()
  const label = parts.join(".") || domain
  return label.length > MAX_LABEL ? `${label.slice(0, MAX_LABEL - 1)}…` : label
}

function levelOf(cell: HeatmapCell) {
  return Math.max(0, Math.min(LEVEL_CLASSES.length - 1, Math.round(cell.level)))
}

function ColumnHeader({ column }: { column: HeatmapColumn }) {
  return (
    <th
      scope="col"
      title={column.truncated ? `${column.domain} – lijst afgekapt, aandeel kan hoger zijn` : column.domain}
      className={cn(
        "p-2 text-center text-xs whitespace-nowrap",
        column.is_customer ? "font-bold text-foreground" : "font-semibold text-muted-foreground"
      )}
    >
      {columnLabel(column.domain)}
      {column.truncated && <span aria-hidden="true">*</span>}
      <span className="sr-only">
        {column.is_customer ? " (klant)" : ""}
        {column.truncated ? " (lijst afgekapt)" : ""}
      </span>
    </th>
  )
}

function HeatmapTable({ heatmap }: { heatmap: Heatmap }) {
  const { columns, rows, universe } = heatmap
  const anyTruncated = columns.some((column) => column.truncated)
  return (
    <>
      <div className="overflow-x-auto">
        <table className="w-full border-separate border-spacing-y-1 text-[13px]" style={{ minWidth: 200 + columns.length * 92 }}>
          <thead>
            <tr>
              <th scope="col" className="w-[200px] p-2 text-left text-xs font-semibold text-muted-foreground">
                Onderwerp
              </th>
              {columns.map((column) => (
                <ColumnHeader key={column.domain} column={column} />
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.topic}>
                <th scope="row" className="py-1 pr-3 pl-2 text-left align-middle font-medium">
                  <span className="break-words">{row.topic}</span>{" "}
                  <span className="text-xs font-normal whitespace-nowrap text-muted-foreground">
                    {formatCount(row.keywords)} {row.keywords === 1 ? "zoekwoord" : "zoekwoorden"}
                  </span>
                </th>
                {row.cells.length === 0 ? (
                  <td colSpan={columns.length} className="px-1 py-1 align-middle">
                    <div className="flex h-8 items-center justify-center rounded-md border border-dashed text-xs text-muted-foreground">
                      te weinig zoekwoorden
                    </div>
                  </td>
                ) : (
                  columns.map((column, index) => {
                    const cell = row.cells[index]
                    return (
                      <td key={column.domain} className="px-1 py-1 align-middle">
                        {cell ? (
                          <div
                            className={cn(
                              "flex h-8 items-center justify-center rounded-md text-xs font-medium tabular-nums",
                              LEVEL_CLASSES[levelOf(cell)],
                              column.is_customer && "ring-2 ring-foreground/20 ring-inset"
                            )}
                          >
                            {Math.round(cell.pct)}%
                          </div>
                        ) : (
                          <div className="flex h-8 items-center justify-center text-xs text-muted-foreground">–</div>
                        )}
                      </td>
                    )
                  })
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 text-xs text-muted-foreground">
        <div className="space-y-0.5">
          {anyTruncated && <p>* lijst afgekapt, aandeel kan hoger zijn</p>}
          <p>
            {formatCount(universe.assigned)} van {formatCount(universe.total)} zoekwoorden ingedeeld, waarvan{" "}
            {formatCount(universe.tracked)} gevolgd.
          </p>
        </div>
        <ul className="flex flex-wrap items-center gap-3" aria-label="Legenda">
          {LEGEND.map((label, level) => (
            <li key={label} className="flex items-center gap-1.5">
              <span className={cn("size-3 rounded-sm", LEVEL_CLASSES[level])} aria-hidden="true" />
              {label}
            </li>
          ))}
        </ul>
      </div>
    </>
  )
}

const MESSAGE_TEXTS = {
  empty: "Er zijn nog geen zoekwoorden om in te delen.",
  not_configured: "Ahrefs of Claude is niet ingesteld, dus de onderwerpen konden niet worden berekend.",
  unavailable: "De sterkte per onderwerp kon niet worden berekend.",
}

/** Kaart "Sterkte per onderwerp": per dienst uit het klantprofiel het aandeel top-10-noteringen. */
export function TopicHeatmap({ heatmap, customerId }: { heatmap: Heatmap; customerId: string }) {
  let content: React.ReactNode
  if (heatmap.state === "no_profile") {
    content = (
      <div className="flex items-start gap-3 rounded-lg border border-dashed px-4 py-5 text-sm">
        <Info className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
        <div className="min-w-0 space-y-1">
          <p className="font-medium">Nog geen onderwerpen</p>
          <p className="text-[13px] text-muted-foreground">
            {heatmap.message ??
              "De onderwerpen zijn de diensten uit het klantprofiel. Vul de diensten in en werk daarna het overzicht bij."}
          </p>
          <Link
            href={customerHref("profiel", customerId)}
            className="inline-block text-[13px] font-semibold underline-offset-2 hover:underline"
          >
            Klantprofiel invullen →
          </Link>
        </div>
      </div>
    )
  } else if (heatmap.state === "ok" && heatmap.rows.length > 0 && heatmap.columns.length > 0) {
    content = <HeatmapTable heatmap={heatmap} />
  } else {
    const state =
      heatmap.state === "not_configured" ? "not_configured" : heatmap.state === "error" ? "unavailable" : "empty"
    content = (
      <CardMessage
        state={state}
        texts={{ ...MESSAGE_TEXTS, ...(heatmap.message ? { [state]: heatmap.message } : {}) }}
        error={heatmap.message}
      />
    )
  }

  return (
    <ResultCard
      id="sterkte-per-onderwerp"
      title="Sterkte per onderwerp"
      description="Aandeel van de zoekwoorden binnen een onderwerp waarop het domein in de top 10 staat."
    >
      {content}
    </ResultCard>
  )
}
