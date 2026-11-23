import { TriangleAlert } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Pill, type Tone } from "@/components/livegang/shared"
import { TrendArrow } from "@/components/klanten/dashboard/trend"
import type {
  CustomerQuickWinRow,
  CustomerQuickWins,
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

const td = "px-2 py-3 align-middle"
const muted = <span className="text-muted-foreground">—</span>

const dateFormat = new Intl.DateTimeFormat("nl-NL", {
  dateStyle: "medium",
  timeZone: "Europe/Amsterdam",
})

function formatDate(value: string | null) {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : dateFormat.format(date)
}

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

function sourceLine(quickWins: CustomerQuickWins) {
  const parts = [
    "Bron: Pro Rank Tracker (gevolgde zoekwoorden) en Ahrefs (overige zoekwoorden, KD).",
  ]
  const date = formatDate(quickWins.fetched_at)
  if (date) parts.push(`Ahrefs-stand van ${date}.`)
  if (quickWins.capped) parts.push(`Uit Ahrefs de top ${quickWins.limit} op zoekvolume.`)
  return parts.join(" ")
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

function StateMessage({ quickWins }: { quickWins: CustomerQuickWins }) {
  const text =
    quickWins.state === "ok"
      ? "Geen zoekwoorden op positie 4–20 in Pro Rank Tracker of Ahrefs."
      : quickWins.message ||
        (quickWins.state === "not_configured"
          ? "De koppelingen met Pro Rank Tracker en Ahrefs zijn niet ingesteld."
          : "De zoekwoorden konden niet worden opgehaald. Probeer het later opnieuw.")

  return (
    <p className="rounded-lg border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
      {text}
    </p>
  )
}

function QuickWinRow({ row }: { row: CustomerQuickWinRow }) {
  const volume = formatNumber(row.volume)
  const chance = CHANCE[row.kans]
  return (
    <tr className="border-b">
      <td className={td}>
        <input
          type="checkbox"
          disabled
          aria-label={`Selecteer ${row.keyword}`}
          className="block size-4 cursor-not-allowed rounded-[4px] accent-primary opacity-50"
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
        <span
          aria-disabled="true"
          title="Binnenkort"
          className="cursor-not-allowed font-semibold whitespace-nowrap text-muted-foreground"
        >
          Analyseer →
        </span>
      </td>
    </tr>
  )
}

export function QuickWinsCard({ quickWins }: { quickWins: CustomerQuickWins }) {
  const ok = quickWins.state === "ok"
  const rows = ok ? quickWins.rows : []
  // Bij "ok" is `message` een waarschuwing, bijv. verversen mislukt en oude stand getoond.
  const warning = ok ? quickWins.message : null

  return (
    <section
      aria-labelledby="quick-wins-title"
      className="flex flex-col gap-4 rounded-xl border bg-card px-6 py-5"
    >
      <div className="space-y-1">
        <h2 id="quick-wins-title" className="text-base font-semibold">
          Quick wins – zoekwoorden op positie 4–20
        </h2>
        <p className="text-[13px] text-muted-foreground">{sourceLine(quickWins)}</p>
      </div>

      {warning && (
        <p className="flex items-start gap-1.5 text-[13px] text-muted-foreground">
          <TriangleAlert
            className="mt-0.5 size-3.5 shrink-0 text-amber-600 dark:text-amber-400"
            aria-hidden="true"
          />
          {warning}
        </p>
      )}

      {rows.length === 0 ? (
        <StateMessage quickWins={quickWins} />
      ) : (
        <>
          <div className="overflow-x-auto">
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
                {rows.map((row, index) => (
                  <QuickWinRow
                    key={`${index}|${row.keyword}`}
                    row={row}
                  />
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-[13px] font-medium text-muted-foreground">
              0 zoekwoorden geselecteerd
            </p>
            <div className="flex items-center gap-2">
              <Pill>Binnenkort</Pill>
              <Button disabled className="font-semibold">
                Analyseer selectie
              </Button>
            </div>
          </div>
        </>
      )}
    </section>
  )
}
