import { TriangleAlert } from "lucide-react"

import { QuickWinsTable } from "@/components/klanten/dashboard/QuickWinsTable"
import type { CustomerQuickWins } from "@/lib/customer-types"

const dateFormat = new Intl.DateTimeFormat("nl-NL", {
  dateStyle: "medium",
  timeZone: "Europe/Amsterdam",
})

function formatDate(value: string | null) {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : dateFormat.format(date)
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

export function QuickWinsCard({
  customerId,
  quickWins,
}: {
  customerId: string
  quickWins: CustomerQuickWins
}) {
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
        <QuickWinsTable customerId={customerId} rows={rows} />
      )}
    </section>
  )
}
