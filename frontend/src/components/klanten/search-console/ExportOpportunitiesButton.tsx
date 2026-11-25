"use client"

import { Download } from "lucide-react"

import { Button } from "@/components/ui/button"
import type { OpportunityRow } from "@/lib/search-console-insights"

type Cell = string | number | null

const HEADERS = [
  "Zoekterm",
  "Pagina",
  "Vertoningen",
  "Klikken",
  "CTR (%)",
  "Verwachte CTR (%)",
  "Positie",
  "Gemiste klikken",
  "Andere pagina's",
  "Advies",
]

/** Getal met decimale komma en zonder duizendtalscheiding, zodat Excel (nl) het als getal leest. */
function csvNumber(value: number, digits: number) {
  return value.toFixed(digits).replace(".", ",")
}

/** Eén CSV-cel: formulebescherming en quotes waar nodig. */
function csvCell(value: Cell) {
  if (value == null) return ""
  let cell = String(value)
  // Tekst die met =, +, - of @ begint, zou Excel als formule uitvoeren.
  if (typeof value === "string" && /^[=+\-@]/.test(cell)) cell = `'${cell}`
  if (/[;"\r\n]/.test(cell)) cell = `"${cell.replace(/"/g, '""')}"`
  return cell
}

function toCsv(rows: OpportunityRow[]) {
  const lines: Cell[][] = [
    HEADERS,
    ...rows.map((row) => [
      row.query,
      row.page,
      row.impressions,
      row.clicks,
      csvNumber(row.ctr * 100, 2),
      row.expected_ctr == null ? null : csvNumber(row.expected_ctr * 100, 2),
      csvNumber(row.position, 1),
      Math.round(row.missed_clicks),
      row.other_pages,
      row.advice,
    ]),
  ]
  return lines.map((line) => line.map(csvCell).join(";")).join("\r\n") + "\r\n"
}

/** Bestandsnaamdeel zonder tekens die een bestandssysteem niet lust. */
function safeName(value: string) {
  return value.replace(/[^a-zA-Z0-9.-]+/g, "-").replace(/^-+|-+$/g, "") || "site"
}

/**
 * Exporteert alle CTR-kansen uit het antwoord (niet alleen de zichtbare rijen) als CSV voor
 * Excel: `;` als scheidingsteken, UTF-8 met BOM, CRLF en decimale komma.
 */
export function ExportOpportunitiesButton({
  rows,
  domain,
  endDate,
  days,
}: {
  rows: OpportunityRow[]
  domain: string
  /** Einddatum van de periode (JJJJ-MM-DD); zonder periode de datum van vandaag. */
  endDate: string | null
  days: number
}) {
  const disabled = rows.length === 0

  function download() {
    const end = endDate ?? new Date().toISOString().slice(0, 10)
    const filename = `ctr-kansen-${safeName(domain)}-${safeName(end)}-${days}d.csv`
    const blob = new Blob(["﻿", toCsv(rows)], { type: "text/csv;charset=utf-8" })
    const url = URL.createObjectURL(blob)
    const link = document.createElement("a")
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  }

  return (
    <Button
      className="font-semibold"
      disabled={disabled}
      onClick={download}
      title={disabled ? "Geen CTR-kansen om te exporteren" : undefined}
    >
      <Download />
      Exporteer kansen
    </Button>
  )
}
