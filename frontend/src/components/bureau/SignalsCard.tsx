"use client"

import { useState } from "react"
import Link from "next/link"

import { EmptyState } from "@/components/analytics/states"
import { Pill, type Tone } from "@/components/livegang/shared"
import { signalHref, type AgencySignal, type SignalKind } from "@/lib/agency-overview"

const KINDS: Record<SignalKind, { label: string; tone: Tone; linkLabel: string }> = {
  daling: { label: "Daling", tone: "red", linkLabel: "Bekijk posities" },
  storing: { label: "Storing", tone: "red", linkLabel: "Bekijk" },
  werk: { label: "Werk", tone: "amber", linkLabel: "Open werkvoorraad" },
  rapport: { label: "Rapport", tone: "blue", linkLabel: "Open rapport" },
}

/** Aantal regels dat zonder uitklappen zichtbaar is. */
const COLLAPSED_ROWS = 8
const LIST_ID = "bureau-signalen"

export const moreButtonClass =
  "self-start rounded-sm text-[13px] font-semibold text-primary underline-offset-4 outline-none hover:underline focus-visible:ring-[3px] focus-visible:ring-ring/50"

function SignalRow({ signal }: { signal: AgencySignal }) {
  const kind = KINDS[signal.kind] ?? { label: signal.kind, tone: "muted" as Tone, linkLabel: "Bekijk" }
  const href = signalHref(signal.link)
  const name = signal.customer_name?.trim() || (signal.customer_id ? "Onbekende klant" : "Bureau")

  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b py-3.5 last:border-b-0 sm:flex-nowrap">
      <div className="w-[72px] shrink-0">
        <Pill tone={kind.tone}>{kind.label}</Pill>
      </div>
      <div className="min-w-0 flex-1 basis-60">
        <p className="text-sm font-semibold break-words">{name}</p>
        <p className="text-[13px] break-words text-muted-foreground">{signal.text}</p>
      </div>
      {href && (
        <Link
          href={href}
          className="shrink-0 rounded-sm text-[13px] font-semibold whitespace-nowrap text-primary underline-offset-4 outline-none hover:underline focus-visible:ring-[3px] focus-visible:ring-ring/50"
        >
          {kind.linkLabel} →
        </Link>
      )}
    </li>
  )
}

/** Kaart "Vraagt aandacht": signalen van ernstig naar minder ernstig (volgorde van de backend). */
export function SignalsCard({ signals }: { signals: AgencySignal[] }) {
  const [expanded, setExpanded] = useState(false)
  const hiddenCount = Math.max(0, signals.length - COLLAPSED_ROWS)
  const visible = expanded ? signals : signals.slice(0, COLLAPSED_ROWS)

  return (
    <section aria-labelledby="bureau-signalen-titel" className="flex flex-col gap-3 rounded-xl border bg-card px-6 py-5">
      <div className="space-y-1">
        <h2 id="bureau-signalen-titel" className="text-base font-semibold">
          Vraagt aandacht
        </h2>
        <p className="text-[13px] text-muted-foreground">
          Automatisch gesignaleerd uit posities, scans, koppelingen, werkvoorraad en rapportages.
        </p>
      </div>

      {signals.length === 0 ? (
        <EmptyState className="py-6">Niets dat aandacht vraagt</EmptyState>
      ) : (
        <ul id={LIST_ID} className="flex flex-col">
          {visible.map((signal) => (
            <SignalRow key={signal.id} signal={signal} />
          ))}
        </ul>
      )}

      {hiddenCount > 0 && (
        <button
          type="button"
          aria-expanded={expanded}
          aria-controls={LIST_ID}
          onClick={() => setExpanded((current) => !current)}
          className={moreButtonClass}
        >
          {expanded
            ? "Minder tonen"
            : `+ ${hiddenCount} ${hiddenCount === 1 ? "ander signaal" : "andere signalen"} tonen`}
        </button>
      )}
    </section>
  )
}
