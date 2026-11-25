"use client"

import { Loader2, Trash2 } from "lucide-react"

import { CardMessage } from "@/components/klanten/analyses/result-parts"
import { selectClass } from "@/components/klanten/analyses/form-controls"
import { formatCount, formatPct } from "@/components/klanten/zoekwoorden/CompetitorKpis"
import { Pill } from "@/components/livegang/shared"
import { Button } from "@/components/ui/button"
import {
  COMPETITOR_TYPE_LABELS,
  type CompetitorRow,
  type CompetitorType,
  type CompetitorsSection,
  type OverlapBasis,
} from "@/lib/keyword-competitors"
import { cn } from "@/lib/utils"

/** Wat de view moet opslaan: altijd beide velden (`null` = oordeel van Claude). */
export type CompetitorChoice = {
  domain: string
  type: CompetitorType | null
  excluded: boolean | null
}

const COLUMNS: { label: string; width?: number; srOnly?: boolean; numeric?: boolean }[] = [
  { label: "Domein" },
  { label: "Type", width: 240 },
  { label: "DR", width: 56, numeric: true },
  { label: "Org. zoekwoorden", width: 128, numeric: true },
  { label: "In top 10", width: 88, numeric: true },
  { label: "Verkeer /mnd", width: 112, numeric: true },
  { label: "Gedeeld", width: 80, numeric: true },
  { label: "Overlap", width: 168 },
  { label: "Acties", width: 48, srOnly: true },
]

const TYPE_PILL: Record<CompetitorType, { tone: "blue" | "green" | "muted"; className?: string }> = {
  landelijk: { tone: "blue" },
  regio: { tone: "muted", className: "bg-indigo-100 text-indigo-800 dark:bg-indigo-900/30 dark:text-indigo-300" },
  lokaal: { tone: "green" },
}

const TYPES: CompetitorType[] = ["landelijk", "regio", "lokaal"]

const td = "px-2 py-3 align-middle"
const num = cn(td, "text-right tabular-nums")

/** Keuze in de lijst per rij → wat er opgeslagen wordt; houdt de andere handmatige keuze vast. */
function choiceFor(row: CompetitorRow, value: string): CompetitorChoice | null {
  const manualType = row.type_source === "manual" ? row.type : null
  const manualExcluded = row.excluded_source === "manual" ? row.excluded : null
  switch (value) {
    case "landelijk":
    case "regio":
    case "lokaal":
      return { domain: row.domain, type: value, excluded: manualExcluded }
    case "exclude":
      return { domain: row.domain, type: manualType, excluded: true }
    case "include":
      return { domain: row.domain, type: manualType, excluded: false }
    case "ai":
      return { domain: row.domain, type: null, excluded: null }
    default:
      return null
  }
}

function TypeCell({
  row,
  disabled,
  onChoice,
}: {
  row: CompetitorRow
  disabled: boolean
  onChoice: (choice: CompetitorChoice) => void
}) {
  const manual = row.type_source === "manual" || row.excluded_source === "manual"
  const manualTitle = [
    row.type_source === "manual" ? "Type handmatig gekozen" : null,
    row.excluded_source === "manual" ? (row.excluded ? "Handmatig uitgesloten" : "Handmatig weer meegeteld") : null,
  ]
    .filter(Boolean)
    .join(" · ")

  return (
    <div className="flex items-center gap-1.5">
      {row.excluded ? (
        <Pill>Uitgesloten</Pill>
      ) : row.type ? (
        <Pill tone={TYPE_PILL[row.type].tone} className={TYPE_PILL[row.type].className}>
          {COMPETITOR_TYPE_LABELS[row.type]}
        </Pill>
      ) : (
        <span className="w-6 text-muted-foreground">–</span>
      )}
      {manual && (
        <span className="text-[11px] text-muted-foreground" title={manualTitle}>
          handmatig
        </span>
      )}
      {/* Werkt als een menu: de lijst springt na een keuze terug op "Wijzig". */}
      <select
        value=""
        disabled={disabled}
        aria-label={`Type van ${row.domain} wijzigen`}
        onChange={(event) => {
          const choice = choiceFor(row, event.target.value)
          if (choice) onChoice(choice)
        }}
        className={cn(
          selectClass,
          "ml-auto h-7 w-[4.5rem] shrink-0 border-transparent bg-transparent px-1.5 text-xs text-muted-foreground shadow-none hover:border-input dark:bg-transparent"
        )}
      >
        <option value="" disabled>
          Wijzig
        </option>
        {TYPES.map((type) => (
          <option key={type} value={type}>
            {COMPETITOR_TYPE_LABELS[type]}
            {!row.excluded && row.type === type ? " ✓" : ""}
          </option>
        ))}
        {row.excluded ? <option value="include">Weer meetellen</option> : <option value="exclude">Uitsluiten</option>}
        <option value="ai" disabled={!manual}>
          Oordeel van Claude volgen
        </option>
      </select>
    </div>
  )
}

function OverlapCell({ row }: { row: CompetitorRow }) {
  if (row.excluded) {
    return <span className="text-xs text-muted-foreground">{row.exclude_reason ?? "uitgesloten"}</span>
  }
  const width = Math.max(0, Math.min(100, row.overlap_pct))
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-20 shrink-0 overflow-hidden rounded-full bg-muted" aria-hidden="true">
        <div className="h-full rounded-full bg-primary" style={{ width: `${width}%` }} />
      </div>
      <span className="tabular-nums">{formatPct(row.overlap_pct)}</span>
    </div>
  )
}

function CompetitorTableRow({
  row,
  busy,
  disabled,
  onChoice,
  onRemove,
}: {
  row: CompetitorRow
  busy: boolean
  disabled: boolean
  onChoice: (choice: CompetitorChoice) => void
  onRemove: (domain: string) => void
}) {
  // Meetellend maar buiten de vijf: licht gedempt (niet in heatmap en KPI's).
  const outsideTop5 = !row.excluded && !row.in_top5 && !row.pending
  return (
    <tr
      className={cn("border-b", outsideTop5 && "text-muted-foreground")}
      title={outsideTop5 ? "Telt niet mee in de top 5" : undefined}
      aria-busy={busy || undefined}
    >
      <td className={cn(td, "min-w-0")}>
        <a
          href={`https://${row.domain}`}
          target="_blank"
          rel="noreferrer noopener"
          className={cn(
            "font-semibold break-all underline-offset-2 hover:underline",
            row.excluded || outsideTop5 ? "text-muted-foreground" : "text-foreground"
          )}
        >
          {row.domain}
        </a>
        {row.origin === "tracked" && (
          <p className="text-[11px] text-muted-foreground">via gevolgde zoekwoorden</p>
        )}
        {row.origin === "manual" && <p className="text-[11px] text-muted-foreground">handmatig toegevoegd</p>}
      </td>
      <td className={td}>
        <TypeCell row={row} disabled={disabled || busy} onChoice={onChoice} />
      </td>
      {row.pending ? (
        <td colSpan={6} className={cn(td, "text-[13px] text-muted-foreground italic")}>
          Nog geen cijfers – werk het overzicht bij
        </td>
      ) : (
        <>
          <td className={num}>{formatCount(row.domain_rating)}</td>
          <td className={num}>{formatCount(row.organic_keywords)}</td>
          <td className={num}>{formatCount(row.top10_keywords)}</td>
          <td className={num}>{formatCount(row.traffic)}</td>
          <td className={num}>{formatCount(row.shared)}</td>
          <td className={td}>
            <OverlapCell row={row} />
          </td>
        </>
      )}
      <td className={cn(td, "text-right")}>
        {row.origin === "manual" && (
          <Button
            variant="ghost"
            size="icon-sm"
            disabled={disabled || busy}
            onClick={() => onRemove(row.domain)}
            aria-label={`${row.domain} verwijderen`}
            title="Verwijderen"
          >
            {busy ? <Loader2 className="animate-spin" aria-hidden="true" /> : <Trash2 aria-hidden="true" />}
          </Button>
        )}
      </td>
    </tr>
  )
}

const EMPTY_TEXTS = {
  empty: "Ahrefs vond geen organische concurrenten voor dit domein. Voeg zelf een concurrent toe.",
  not_configured: "Ahrefs is niet ingesteld of de klant heeft geen website-adres.",
  unavailable: "De concurrenten konden niet worden opgehaald.",
}

/** Tabel "Wie concurreert er in Google?" met de keuzes per rij. */
export function CompetitorsTable({
  section,
  overlapBasis,
  trackedSample,
  busyDomain,
  disabled,
  onChoice,
  onRemove,
}: {
  section: CompetitorsSection
  overlapBasis: OverlapBasis
  trackedSample: number
  /** Domein waarvoor nu een wijziging wordt opgeslagen. */
  busyDomain: string | null
  /** Alle keuzes uit (bijv. tijdens een andere wijziging). */
  disabled: boolean
  onChoice: (choice: CompetitorChoice) => void
  onRemove: (domain: string) => void
}) {
  const { rows } = section

  if (rows.length === 0) {
    const state =
      section.state === "not_configured" ? "not_configured" : section.state === "error" ? "unavailable" : "empty"
    return (
      <CardMessage
        state={state}
        texts={section.message ? { ...EMPTY_TEXTS, [state]: section.message } : EMPTY_TEXTS}
        error={section.message}
      />
    )
  }

  const hasNumbers = rows.some((row) => !row.pending)

  return (
    <>
      {section.message && (section.state === "error" || section.state === "not_configured") && (
        <p className="text-[13px] text-muted-foreground">{section.message}</p>
      )}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[1120px] table-fixed text-[13px]">
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
                  {column.srOnly ? <span className="sr-only">{column.label}</span> : column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <CompetitorTableRow
                key={row.domain}
                row={row}
                busy={busyDomain === row.domain}
                disabled={disabled}
                onChoice={onChoice}
                onRemove={onRemove}
              />
            ))}
          </tbody>
        </table>
      </div>
      {overlapBasis === "tracked" && hasNumbers && (
        <p className="text-xs text-muted-foreground">
          Gedeeld en overlap op basis van {formatCount(trackedSample)} gevolgde zoekwoorden.
        </p>
      )}
    </>
  )
}
