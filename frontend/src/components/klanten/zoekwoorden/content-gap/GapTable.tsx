import { formatInt } from "@/components/klanten/analyses/result-parts"
import { Pill, type Tone } from "@/components/livegang/shared"
import { domainLabel, intentLabel, type GapKeyword, type IntentLabel } from "@/lib/keyword-content-gap"
import { cn } from "@/lib/utils"

// Kolombreedtes in px (inclusief de opvulling van de cel); het zoekwoord krijgt de rest.
const KEYWORD_MIN_WIDTH = 240
const VOLUME_WIDTH = 86
const KD_WIDTH = 60
const INTENT_WIDTH = 126
const DOMAIN_WIDTH = 86
const CUSTOMER_WIDTH = 80

const INTENT_PILL: Record<IntentLabel, { tone: Tone; className?: string }> = {
  Commercieel: { tone: "blue" },
  Informatief: { tone: "muted" },
  Lokaal: { tone: "green" },
  Navigatie: { tone: "muted", className: "bg-indigo-100 text-indigo-800 dark:bg-indigo-900/30 dark:text-indigo-300" },
}

const th = "bg-muted p-2 text-left text-xs font-semibold text-muted-foreground first:rounded-l-md last:rounded-r-md"
const td = "px-2 py-[11px] align-middle"
const num = cn(td, "tabular-nums")

/**
 * Positie als "#4". Concurrenten: 1–3 groen, 4–10 donker. De klant staat hier per definitie
 * niet in de top 10: een positie daarbuiten is oranje. Geen positie: "—".
 */
function Position({ value, own = false }: { value: number | null; own?: boolean }) {
  if (value == null) {
    return (
      <span className="text-muted-foreground/60">
        —<span className="sr-only">{own ? "Niet gevonden" : "Niet in de top 10"}</span>
      </span>
    )
  }
  const rank = Math.round(value)
  const className =
    rank <= 3
      ? "font-semibold text-green-700 dark:text-green-400"
      : rank <= 10
        ? "font-semibold text-foreground"
        : own
          ? "font-semibold text-orange-600 dark:text-orange-400"
          : "text-muted-foreground"
  return <span className={cn("tabular-nums", className)}>#{rank}</span>
}

function IntentBadge({ intents }: { intents: string[] }) {
  const label = intentLabel(intents)
  if (!label) return <span className="text-muted-foreground">—</span>
  const pill = INTENT_PILL[label]
  return (
    <Pill tone={pill.tone} className={pill.className}>
      {label}
    </Pill>
  )
}

/** Kop met het domein zonder "www." en extensie; het volledige domein staat in de `title`. */
function DomainHeader({ domain, label }: { domain: string; label?: string }) {
  return (
    <th scope="col" className={th} title={domain}>
      <span className="block truncate">{label ?? domainLabel(domain)}</span>
    </th>
  )
}

/** Tabel "Gap-zoekwoorden": één kolom per concurrent en de klant als laatste kolom. */
export function GapTable({
  keywords,
  competitors,
  customerName,
  customerDomain,
}: {
  keywords: GapKeyword[]
  /** Domeinen in kolomvolgorde. */
  competitors: string[]
  customerName: string
  customerDomain: string
}) {
  const minWidth =
    KEYWORD_MIN_WIDTH + VOLUME_WIDTH + KD_WIDTH + INTENT_WIDTH + DOMAIN_WIDTH * competitors.length + CUSTOMER_WIDTH

  return (
    <div className="overflow-x-auto">
      <table className="w-full table-fixed text-[13px]" style={{ minWidth }}>
        <colgroup>
          <col />
          <col style={{ width: VOLUME_WIDTH }} />
          <col style={{ width: KD_WIDTH }} />
          <col style={{ width: INTENT_WIDTH }} />
          {competitors.map((domain) => (
            <col key={domain} style={{ width: DOMAIN_WIDTH }} />
          ))}
          <col style={{ width: CUSTOMER_WIDTH }} />
        </colgroup>
        <thead>
          <tr>
            <th scope="col" className={th}>
              Zoekwoord
            </th>
            <th scope="col" className={th}>
              Volume
            </th>
            <th scope="col" className={th}>
              KD
            </th>
            <th scope="col" className={th}>
              Intentie
            </th>
            {competitors.map((domain) => (
              <DomainHeader key={domain} domain={domain} />
            ))}
            <DomainHeader domain={customerDomain || customerName} label={customerName} />
          </tr>
        </thead>
        <tbody>
          {keywords.map((row) => (
            <tr key={row.keyword} className="border-b">
              <th scope="row" className={cn(td, "text-left font-semibold break-words")}>
                {row.keyword}
              </th>
              <td className={num}>{formatInt(row.volume)}</td>
              <td className={num}>{formatInt(row.kd)}</td>
              <td className={td}>
                <IntentBadge intents={row.intents} />
              </td>
              {competitors.map((domain) => (
                <td key={domain} className={td}>
                  <Position value={row.positions[domain] ?? null} />
                </td>
              ))}
              <td className={td}>
                <Position value={row.own_position} own />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
