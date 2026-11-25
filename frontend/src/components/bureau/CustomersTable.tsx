"use client"

import { useState } from "react"
import Link from "next/link"

import { moreButtonClass } from "@/components/bureau/SignalsCard"
import { EmptyState } from "@/components/analytics/states"
import { TrendArrow } from "@/components/klanten/dashboard/trend"
import { Pill } from "@/components/livegang/shared"
import { customerHref } from "@/lib/active-customer"
import type { AgencyCustomer, RankState } from "@/lib/agency-overview"
import { workBoardHref } from "@/lib/work-queue"
import { cn } from "@/lib/utils"

// Klant deelt de resterende ruimte; de rest heeft een vaste breedte.
const COLUMNS: { label: string; width?: number }[] = [
  { label: "Klant" },
  { label: "Top 10", width: 104 },
  { label: "Trend 30d", width: 96 },
  { label: "Open taken", width: 104 },
  { label: "Status", width: 112 },
]

/** Uitleg bij "–" in de kolom Top 10. */
const RANK_REASONS: Record<Exclude<RankState, "ok">, string> = {
  not_configured: "De koppeling met ProRankTracker is niet ingesteld.",
  not_tracked: "Deze klant wordt niet gevolgd in ProRankTracker.",
  error: "De posities konden niet worden opgehaald uit ProRankTracker.",
  missing: "De posities zijn nog niet opgehaald.",
}

/** Aantal rijen dat zonder uitklappen zichtbaar is. */
const COLLAPSED_ROWS = 10
const TABLE_ID = "bureau-klanten"

const td = "px-2 py-3 align-middle"
const dash = <span className="text-muted-foreground">–</span>
const linkClass =
  "rounded-sm underline-offset-2 outline-none hover:underline focus-visible:ring-[3px] focus-visible:ring-ring/50"

function Top10({ customer }: { customer: AgencyCustomer }) {
  if (customer.rank_state !== "ok" || customer.top10 == null || customer.keywords == null) {
    const reason =
      customer.rank_state === "ok" ? "Er zijn geen posities bekend." : RANK_REASONS[customer.rank_state]
    return (
      <span className="cursor-help text-muted-foreground" title={reason}>
        –<span className="sr-only"> ({reason})</span>
      </span>
    )
  }
  return (
    <span className="tabular-nums">
      {customer.top10.toLocaleString("nl-NL")} / {customer.keywords.toLocaleString("nl-NL")}
    </span>
  )
}

function Trend({ customer }: { customer: AgencyCustomer }) {
  const delta = customer.rank_state === "ok" ? customer.top10_delta : null
  if (!delta) return dash
  return (
    <span
      className={cn(
        "font-medium",
        delta > 0 ? "text-green-700 dark:text-green-400" : "text-red-700 dark:text-red-400"
      )}
      title="Verschil in zoekwoorden in de top 10 t.o.v. een maand geleden"
    >
      <TrendArrow value={delta} />
    </span>
  )
}

function CustomerRow({ customer }: { customer: AgencyCustomer }) {
  const attention = customer.signal_count > 0
  return (
    <tr className="border-b">
      <td className={cn(td, "font-semibold break-words")}>
        <Link href={customerHref("home", customer.id)} className={linkClass}>
          {customer.name}
        </Link>
      </td>
      <td className={td}>
        <Top10 customer={customer} />
      </td>
      <td className={cn(td, "tabular-nums")}>
        <Trend customer={customer} />
      </td>
      <td className={cn(td, "tabular-nums")}>
        <Link
          href={workBoardHref({ customerId: customer.id })}
          className={cn(linkClass, customer.open_tasks === 0 && "text-muted-foreground")}
          aria-label={`${customer.open_tasks} open ${customer.open_tasks === 1 ? "taak" : "taken"} van ${customer.name} in de werkvoorraad`}
        >
          {customer.open_tasks.toLocaleString("nl-NL")}
        </Link>
      </td>
      <td className={td}>
        {attention ? <Pill tone="red">Aandacht</Pill> : <Pill tone="green">Op koers</Pill>}
      </td>
    </tr>
  )
}

/** Kaart "Klanten": één rij per klant, in de volgorde van de backend (klanten met signalen eerst). */
export function CustomersTable({ customers }: { customers: AgencyCustomer[] }) {
  const [expanded, setExpanded] = useState(false)
  const hiddenCount = Math.max(0, customers.length - COLLAPSED_ROWS)
  const visible = expanded ? customers : customers.slice(0, COLLAPSED_ROWS)

  return (
    <section aria-labelledby="bureau-klanten-titel" className="flex flex-col gap-4 rounded-xl border bg-card px-6 py-5">
      <div className="space-y-1">
        <h2 id="bureau-klanten-titel" className="text-base font-semibold">
          Klanten
        </h2>
        <p className="text-[13px] text-muted-foreground">Klanten met signalen eerst. Posities uit ProRankTracker.</p>
      </div>

      {customers.length === 0 ? (
        <EmptyState className="py-6">Nog geen klanten</EmptyState>
      ) : (
        <div id={TABLE_ID} className="overflow-x-auto">
          <table className="w-full min-w-[560px] table-fixed text-[13px]">
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
                    className="bg-muted p-2 text-left text-xs font-semibold text-muted-foreground first:rounded-l-md last:rounded-r-md"
                  >
                    {column.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visible.map((customer) => (
                <CustomerRow key={customer.id} customer={customer} />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {hiddenCount > 0 && (
        <button
          type="button"
          aria-expanded={expanded}
          aria-controls={TABLE_ID}
          onClick={() => setExpanded((current) => !current)}
          className={moreButtonClass}
        >
          {expanded
            ? "Minder tonen"
            : `+ ${hiddenCount} ${hiddenCount === 1 ? "andere klant" : "andere klanten"} tonen`}
        </button>
      )}
    </section>
  )
}
