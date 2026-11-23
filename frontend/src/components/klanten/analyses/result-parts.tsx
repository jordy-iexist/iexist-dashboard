// Gedeelde bouwstenen voor het resultaat van een concurrentieanalyse: de kaart in de stijl van
// het klantdashboard, de melding voor een kaart zonder inhoud en de getalnotaties.

import { Loader2 } from "lucide-react"

import { CARD_STATE_LABELS, type CardState } from "@/lib/competitor-analysis"
import { cn } from "@/lib/utils"

/** Toestand van een kaart: de vier uit `cardState`, plus "nog bezig" tijdens een lopende run. */
export type ResultCardState = CardState | "pending"

/** Kaart met titel en toelichting, zelfde stijl als de kaarten op het klantdashboard. */
export function ResultCard({
  id,
  title,
  description,
  aside,
  className,
  children,
}: {
  /** Basis voor de id van de titel (`aria-labelledby`). */
  id: string
  title: React.ReactNode
  description?: React.ReactNode
  aside?: React.ReactNode
  className?: string
  children: React.ReactNode
}) {
  const titleId = `${id}-title`
  return (
    <section aria-labelledby={titleId} className={cn("flex min-w-0 flex-col gap-4 rounded-xl border bg-card px-6 py-5", className)}>
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1">
        <div className="min-w-0 space-y-1">
          <h2 id={titleId} className="text-base font-semibold">
            {title}
          </h2>
          {description && <p className="text-[13px] text-muted-foreground">{description}</p>}
        </div>
        {aside}
      </div>
      {children}
    </section>
  )
}

/**
 * Inhoud van een kaart zonder gegevens. `texts` geeft per toestand de zin wat dat betekent;
 * bij "niet beschikbaar" gaat een meegegeven foutmelding (`error`) voor.
 */
export function CardMessage({
  state,
  texts,
  error,
}: {
  state: Exclude<ResultCardState, "filled">
  texts: Partial<Record<Exclude<ResultCardState, "filled">, string>>
  error?: string | null
}) {
  if (state === "pending") {
    return (
      <p role="status" className="flex items-center gap-2 rounded-lg border border-dashed px-4 py-6 text-sm text-muted-foreground">
        <Loader2 className="size-4 shrink-0 animate-spin" aria-hidden="true" />
        {texts.pending ?? "Wordt nog geanalyseerd…"}
      </p>
    )
  }
  const sentence = state === "unavailable" && error ? error : texts[state]
  return (
    <div className="rounded-lg border border-dashed px-4 py-5 text-sm">
      <p className="font-medium">{CARD_STATE_LABELS[state]}</p>
      {sentence && <p className="mt-1 text-[13px] text-muted-foreground">{sentence}</p>}
    </div>
  )
}

// --- Notaties -------------------------------------------------------------------------------

/** Domein en pad zonder protocol en "www.", bijv. "iexist.nl/seo". */
export function shortUrl(url: string) {
  try {
    const parsed = new URL(url)
    const host = parsed.hostname.replace(/^www\./, "")
    const path = parsed.pathname.replace(/\/+$/, "")
    return `${host}${path}${parsed.search}`
  } catch {
    return url.replace(/^https?:\/\/(www\.)?/, "").replace(/\/+$/, "")
  }
}

/** Domein zonder "www." en in kleine letters, om domeinen te vergelijken. */
export function bareDomain(domain: string) {
  return domain.trim().toLowerCase().replace(/^https?:\/\//, "").replace(/^www\./, "").replace(/\/.*$/, "")
}

/** Geheel getal in Nederlandse notatie ("4.400"); null = "—". */
export function formatInt(value: number | null | undefined) {
  return value == null ? "—" : Math.round(value).toLocaleString("nl-NL")
}

/** Kort getal: 2400 → "2,4k", 24000 → "24k"; onder de 1000 gewoon het getal. */
export function formatCompact(value: number | null | undefined) {
  if (value == null) return "—"
  if (Math.abs(value) < 1000) return formatInt(value)
  if (Math.abs(value) >= 1_000_000) {
    const millions = value / 1_000_000
    return `${millions.toLocaleString("nl-NL", { maximumFractionDigits: Math.abs(millions) < 10 ? 1 : 0 })}M`
  }
  const thousands = value / 1000
  return `${thousands.toLocaleString("nl-NL", { maximumFractionDigits: Math.abs(thousands) < 10 ? 1 : 0 })}k`
}

/** LCP in seconden met één decimaal: 1800 → "1,8 s". */
export function formatLcp(ms: number | null | undefined) {
  if (ms == null) return "—"
  return `${(ms / 1000).toLocaleString("nl-NL", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} s`
}

const shortDateFormat = new Intl.DateTimeFormat("nl-NL", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "Europe/Amsterdam",
})

/** Alleen de datum: "14 nov 2026"; null bij een lege of ongeldige waarde. */
export function formatShortDate(value: string | null | undefined) {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : shortDateFormat.format(date).replace(/\.$/, "").replace(". ", " ")
}

const usdFormat = new Intl.NumberFormat("nl-NL", { style: "currency", currency: "USD", maximumFractionDigits: 2 })
const eurFormat = new Intl.NumberFormat("nl-NL", { style: "currency", currency: "EUR", maximumFractionDigits: 2 })

export function formatUsd(value: number) {
  return usdFormat.format(value)
}

export function formatEur(value: number) {
  return eurFormat.format(value)
}

/** ✓ of – met een tekst voor schermlezers; null = onbekend ("—"). */
export function YesNo({ value, yes = "Ja", no = "Nee", title }: { value: boolean | null | undefined; yes?: string; no?: string; title?: string }) {
  if (value == null) {
    return (
      <span className="text-muted-foreground" title={title ?? "Onbekend"}>
        —<span className="sr-only">{title ?? "Onbekend"}</span>
      </span>
    )
  }
  return (
    <span className={value ? "text-green-700 dark:text-green-400" : "text-muted-foreground"} title={title}>
      <span aria-hidden="true">{value ? "✓" : "–"}</span>
      <span className="sr-only">{value ? yes : no}</span>
    </span>
  )
}
