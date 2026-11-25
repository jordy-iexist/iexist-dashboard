"use client"

import { useState } from "react"
import Link from "next/link"
import { ChevronDown, ChevronUp } from "lucide-react"

import { formatInt } from "@/components/klanten/analyses/result-parts"
import { formatCtr, formatPosition, urlPath } from "@/components/klanten/search-console/format"
import { Pill } from "@/components/livegang/shared"
import { Button } from "@/components/ui/button"
import { newAnalysisHref } from "@/lib/competitor-analysis"
import type { OpportunityRow } from "@/lib/search-console-insights"
import { cn } from "@/lib/utils"

// Kolommen zonder breedte (Zoekterm en Pagina) delen de resterende ruimte.
const COLUMNS: { label: string; width?: number; numeric?: boolean }[] = [
  { label: "Zoekterm" },
  { label: "Pagina" },
  { label: "Vertoningen", width: 104, numeric: true },
  { label: "Klikken", width: 80, numeric: true },
  { label: "CTR", width: 72, numeric: true },
  { label: "Verwachte CTR", width: 112, numeric: true },
  { label: "Positie", width: 72, numeric: true },
  { label: "Advies", width: 280 },
]

/** Aantal rijen dat zonder uitklappen zichtbaar is. */
const COLLAPSED_ROWS = 10
const TABLE_ID = "ctr-kansen-tabel"

const td = "px-2 py-3 align-top"
const numericTd = cn(td, "text-right tabular-nums")

function OpportunityTableRow({ row, customerId }: { row: OpportunityRow; customerId: string }) {
  return (
    <tr className="border-b">
      <td className={cn(td, "font-medium break-words")}>{row.query}</td>
      <td className={cn(td, "max-w-0")}>
        <a
          href={row.page}
          target="_blank"
          rel="noreferrer noopener"
          title={row.page}
          className="block truncate text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
        >
          {urlPath(row.page)}
        </a>
        {row.other_pages > 0 && (
          <p className="mt-0.5 text-xs text-muted-foreground">
            + {formatInt(row.other_pages)} andere {row.other_pages === 1 ? "pagina" : "pagina's"}
          </p>
        )}
      </td>
      <td className={numericTd}>{formatInt(row.impressions)}</td>
      <td className={numericTd}>{formatInt(row.clicks)}</td>
      <td className={cn(numericTd, "font-semibold text-red-700 dark:text-red-400")}>
        {formatCtr(row.ctr)}
      </td>
      <td className={cn(numericTd, "text-muted-foreground")}>{formatCtr(row.expected_ctr)}</td>
      <td className={numericTd}>{formatPosition(row.position)}</td>
      <td className={cn(td, "text-[13px]")}>
        {row.advice && <span>{row.advice}</span>}
        {row.advice_code === "improve_position" && (
          <>
            {row.advice && " "}
            <Link
              href={newAnalysisHref(customerId, [row.query])}
              className="font-semibold whitespace-nowrap underline-offset-2 hover:underline"
            >
              Analyseer →
            </Link>
          </>
        )}
      </td>
    </tr>
  )
}

/** Afgerond potentieel uit de backend; `null` of < 5 → geen regel. */
function PotentialLine({ potential }: { potential: number | null }) {
  if (potential == null || potential < 5) return <span />
  return (
    <p className="text-[13px] text-muted-foreground">
      Geschat potentieel bij verwachte CTR:{" "}
      <span className="font-semibold text-green-700 tabular-nums dark:text-green-400">
        + ± {formatInt(potential)} klikken per maand
      </span>
    </p>
  )
}

/** Tabel met de CTR-kansen: eerst 10 rijen, "Bekijk meer" toont de rest. */
export function OpportunitiesTable({
  customerId,
  rows,
  potentialClicksPerMonth,
}: {
  customerId: string
  rows: OpportunityRow[]
  potentialClicksPerMonth: number | null
}) {
  const [expanded, setExpanded] = useState(false)
  const hiddenCount = Math.max(0, rows.length - COLLAPSED_ROWS)
  const visibleRows = expanded ? rows : rows.slice(0, COLLAPSED_ROWS)

  return (
    <>
      <div id={TABLE_ID} className="overflow-x-auto">
        <table className="w-full min-w-[1080px] table-fixed text-[13px]">
          <colgroup>
            {COLUMNS.map((column) => (
              <col key={column.label} style={column.width ? { width: column.width } : undefined} />
            ))}
          </colgroup>
          <thead>
            <tr>
              {COLUMNS.map((column) => (
                <th
                  key={column.label}
                  scope="col"
                  className={cn(
                    "bg-muted p-2 text-xs font-semibold text-muted-foreground first:rounded-l-md last:rounded-r-md",
                    column.numeric ? "text-right" : "text-left"
                  )}
                >
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visibleRows.map((row, index) => (
              <OpportunityTableRow key={`${index}|${row.query}|${row.page}`} row={row} customerId={customerId} />
            ))}
          </tbody>
        </table>
      </div>

      {hiddenCount > 0 && (
        <div className="flex justify-center">
          <Button
            variant="ghost"
            size="sm"
            aria-expanded={expanded}
            aria-controls={TABLE_ID}
            onClick={() => setExpanded((current) => !current)}
            className="font-medium text-muted-foreground"
          >
            {expanded ? "Bekijk minder" : `Bekijk meer (${hiddenCount})`}
            {expanded ? (
              <ChevronUp className="size-4" aria-hidden="true" />
            ) : (
              <ChevronDown className="size-4" aria-hidden="true" />
            )}
          </Button>
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <PotentialLine potential={potentialClicksPerMonth} />
        <div className="flex flex-wrap items-center gap-2">
          <Pill>Binnenkort</Pill>
          <Button variant="outline" disabled title="Binnenkort">
            Laat Claude titles voorstellen
          </Button>
          <Button disabled title="Binnenkort" className="font-semibold">
            Maak taken ({rows.length.toLocaleString("nl-NL")})
          </Button>
        </div>
      </div>
    </>
  )
}
