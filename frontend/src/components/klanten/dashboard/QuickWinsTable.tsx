"use client"

import { useState } from "react"
import Link from "next/link"
import { ChevronDown, ChevronUp } from "lucide-react"

import { checkboxClass } from "@/components/klanten/analyses/form-controls"
import { Pill, type Tone } from "@/components/livegang/shared"
import { TrendArrow } from "@/components/klanten/dashboard/trend"
import { Button } from "@/components/ui/button"
import { MAX_KEYWORDS, newAnalysisHref } from "@/lib/competitor-analysis"
import type {
  CustomerQuickWinRow,
  QuickWinChance,
  QuickWinSource,
} from "@/lib/customer-types"
import { cn } from "@/lib/utils"

// Kolommen zonder breedte (Zoekwoord en Rankende URL) delen de resterende ruimte.
const COLUMNS: { label: string; width?: number; srOnly?: boolean }[] = [
  { label: "Selecteer", width: 32, srOnly: true },
  { label: "Zoekwoord" },
  { label: "Bron", width: 72 },
  { label: "Positie", width: 72 },
  { label: "Trend 30d", width: 84 },
  { label: "Volume", width: 84 },
  { label: "KD", width: 56 },
  { label: "Rankende URL" },
  { label: "Kans", width: 88 },
  { label: "Actie", width: 112 },
]

const CHANCE: Record<QuickWinChance, { label: string; tone: Tone }> = {
  hoog: { label: "Hoog", tone: "green" },
  middel: { label: "Middel", tone: "amber" },
  laag: { label: "Laag", tone: "muted" },
}

const SOURCE: Record<QuickWinSource, { label: string; title: string }> = {
  prt: { label: "PRT", title: "Gevolgd in Pro Rank Tracker" },
  ahrefs: { label: "Ahrefs", title: "Gevonden door Ahrefs" },
  both: { label: "Beide", title: "Positie uit Pro Rank Tracker, KD uit Ahrefs" },
}

/** Aantal rijen dat zonder uitklappen zichtbaar is. */
const COLLAPSED_ROWS = 10
const TABLE_ID = "quick-wins-tabel"

const td = "px-2 py-3 align-middle"
const muted = <span className="text-muted-foreground">—</span>

function formatNumber(value: number | null) {
  return value == null ? null : value.toLocaleString("nl-NL")
}

/** Pad met query van een URL; bij een ongeldige URL de tekst zelf. */
function urlPath(url: string) {
  try {
    const parsed = new URL(url)
    return `${parsed.pathname}${parsed.search}`
  } catch {
    return url
  }
}

function Trend({ delta }: { delta: number | null }) {
  if (!delta) return <span className="text-muted-foreground">–</span>
  return (
    <span
      className={cn(
        "font-medium",
        delta > 0 ? "text-green-700 dark:text-green-400" : "text-red-700 dark:text-red-400"
      )}
    >
      <TrendArrow value={delta} />
    </span>
  )
}

function QuickWinRow({
  row,
  customerId,
  selected,
  onSelectedChange,
}: {
  row: CustomerQuickWinRow
  customerId: string
  selected: boolean
  onSelectedChange: (selected: boolean) => void
}) {
  const volume = formatNumber(row.volume)
  const chance = CHANCE[row.kans]
  return (
    <tr className={cn("border-b", selected && "bg-muted/40")}>
      <td className={td}>
        <input
          type="checkbox"
          checked={selected}
          onChange={(event) => onSelectedChange(event.target.checked)}
          aria-label={`Selecteer ${row.keyword}`}
          className={checkboxClass}
        />
      </td>
      <td className={cn(td, "font-medium break-words")}>{row.keyword}</td>
      <td className={cn(td, "text-xs text-muted-foreground")} title={SOURCE[row.source].title}>
        {SOURCE[row.source].label}
      </td>
      <td className={cn(td, "font-semibold tabular-nums")}>{row.position}</td>
      <td className={cn(td, "tabular-nums")}>
        <Trend delta={row.delta} />
      </td>
      <td className={cn(td, "tabular-nums")}>{volume ?? muted}</td>
      <td className={cn(td, "tabular-nums")}>{row.kd ?? muted}</td>
      <td className={cn(td, "max-w-0")}>
        {row.url ? (
          <a
            href={row.url}
            target="_blank"
            rel="noreferrer noopener"
            title={row.url}
            className="block truncate text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
          >
            {urlPath(row.url)}
          </a>
        ) : (
          muted
        )}
      </td>
      <td className={td}>
        <Pill tone={chance.tone}>{chance.label}</Pill>
      </td>
      <td className={td}>
        <Link
          href={newAnalysisHref(customerId, [row.keyword])}
          className="font-semibold whitespace-nowrap underline-offset-2 hover:underline"
        >
          Analyseer →
        </Link>
      </td>
    </tr>
  )
}

/** Tabel van de Quick wins met selectie; "Analyseer selectie" opent de wizard met die zoekwoorden. */
export function QuickWinsTable({
  customerId,
  rows,
}: {
  customerId: string
  rows: CustomerQuickWinRow[]
}) {
  // Op zoekwoord, in de volgorde van aanvinken (zo komen ze in de wizard).
  const [selected, setSelected] = useState<string[]>([])

  function toggle(keyword: string, checked: boolean) {
    setSelected((current) =>
      checked
        ? current.includes(keyword)
          ? current
          : [...current, keyword]
        : current.filter((item) => item !== keyword)
    )
  }

  // Eerst de bovenste rijen; "Bekijk meer" klapt de rest uit en weer in.
  const [expanded, setExpanded] = useState(false)
  const hiddenCount = Math.max(0, rows.length - COLLAPSED_ROWS)
  const visibleRows = expanded ? rows : rows.slice(0, COLLAPSED_ROWS)

  const count = selected.length
  const tooMany = count > MAX_KEYWORDS

  return (
    <>
      <div id={TABLE_ID} className="overflow-x-auto">
        <table className="w-full min-w-[1000px] table-fixed text-[13px]">
          <colgroup>
            {COLUMNS.map((column) => (
              <col
                key={column.label}
                style={column.width ? { width: column.width } : undefined}
              />
            ))}
          </colgroup>
          <thead>
            <tr>
              {COLUMNS.map((column) => (
                <th
                  key={column.label}
                  scope="col"
                  className="bg-muted p-2 text-left text-xs font-semibold text-muted-foreground first:rounded-l-md last:rounded-r-md"
                >
                  {column.srOnly ? <span className="sr-only">{column.label}</span> : column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visibleRows.map((row, index) => (
              <QuickWinRow
                key={`${index}|${row.keyword}`}
                row={row}
                customerId={customerId}
                selected={selected.includes(row.keyword)}
                onSelectedChange={(checked) => toggle(row.keyword, checked)}
              />
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
        <div className="space-y-0.5">
          <p className="text-[13px] font-medium text-muted-foreground" aria-live="polite">
            {count} {count === 1 ? "zoekwoord" : "zoekwoorden"} geselecteerd
          </p>
          {tooMany && (
            <p role="status" className="text-[13px] text-amber-700 dark:text-amber-400">
              Een analyse kan maximaal {MAX_KEYWORDS} zoekwoorden bevatten. Haal er{" "}
              {count - MAX_KEYWORDS} weg.
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          {count > 0 && (
            <Button variant="ghost" size="sm" onClick={() => setSelected([])}>
              Selectie wissen
            </Button>
          )}
          {count === 0 || tooMany ? (
            <Button disabled className="font-semibold">
              Analyseer selectie
            </Button>
          ) : (
            <Button asChild className="font-semibold">
              <Link href={newAnalysisHref(customerId, selected)}>Analyseer selectie</Link>
            </Button>
          )}
        </div>
      </div>
    </>
  )
}
