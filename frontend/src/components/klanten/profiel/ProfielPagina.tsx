"use client"

// Gedeelde opbouw van de pagina's Klantprofiel (bewerken) en Klant toevoegen (aanmaken):
// formulierstate met open kaarten, de kop, de melding en de kaarten in twee kolommen.

import Link from "next/link"
import { useEffect, useState } from "react"
import { Sparkles } from "lucide-react"

import { Pill } from "@/components/livegang/shared"
import { Button } from "@/components/ui/button"

import { BedrijfCard, BewijsCard, DienstenCard, UspsCard } from "./BedrijfKaarten"
import { type CardId, type ProfielForm, type UpdateField } from "./profiel-form"
import { RegelsCard, ToneCard } from "./SchrijfKaarten"
import { TrajectCard } from "./TrajectKaart"

// --- State ------------------------------------------------------------------------------------

/** Eén formulierstate voor de hele pagina, plus welke kaarten in bewerkstand staan. */
export function useProfielForm(initialForm: () => ProfielForm, initialOpen: CardId[] = []) {
  const [form, setForm] = useState<ProfielForm>(initialForm)
  const [openCards, setOpenCards] = useState<ReadonlySet<CardId>>(() => new Set(initialOpen))

  const update: UpdateField = (key, value) => {
    setForm((current) => ({ ...current, [key]: value }))
  }

  const toggleCard = (card: CardId) => {
    setOpenCards((current) => {
      const next = new Set(current)
      if (next.has(card)) next.delete(card)
      else next.add(card)
      return next
    })
  }

  return { form, setForm, update, openCards, setOpenCards, toggleCard }
}

/**
 * Standaardwaarschuwing van de browser bij sluiten of herladen zolang `active` waar is.
 * Navigatie binnen het dashboard wordt bewust niet onderschept.
 */
export function useBeforeUnloadWarning(active: boolean) {
  useEffect(() => {
    if (!active) return
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ""
    }
    window.addEventListener("beforeunload", warn)
    return () => window.removeEventListener("beforeunload", warn)
  }, [active])
}

// --- Meldingen --------------------------------------------------------------------------------

export type Feedback = { type: "success" | "error"; message: string } | null

export type ErrorResponse = { error?: string }

export function getErrorMessage(payload: ErrorResponse | null, fallback: string): string {
  return payload?.error?.trim() ? payload.error : fallback
}

export function FeedbackMessage({ feedback }: { feedback: Feedback }) {
  if (!feedback) return null
  return (
    <div
      role={feedback.type === "error" ? "alert" : "status"}
      className={`rounded-xl px-4 py-3 text-sm ${
        feedback.type === "success"
          ? "bg-green-50 text-green-700 dark:bg-green-900/30 dark:text-green-300"
          : "bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-300"
      }`}
    >
      {feedback.message}
    </div>
  )
}

// --- Kop --------------------------------------------------------------------------------------

export type Crumb = { label: string; href?: string }

/** Kruimelpad; het laatste item is de huidige pagina. */
export function Breadcrumb({ items }: { items: Crumb[] }) {
  const linkClass = "underline-offset-2 hover:text-foreground hover:underline"
  return (
    <nav aria-label="Kruimelpad">
      <ol className="flex flex-wrap items-center gap-1.5 text-[13px] text-muted-foreground">
        {items.map((item, index) => {
          const last = index === items.length - 1
          return (
            <li key={`${index}-${item.label}`} className="flex min-w-0 items-center gap-1.5">
              {index > 0 && <span aria-hidden="true">/</span>}
              {last || !item.href ? (
                <span aria-current={last ? "page" : undefined} className={last ? "text-foreground" : undefined}>
                  {item.label}
                </span>
              ) : (
                <Link href={item.href} className={`break-words ${linkClass}`}>
                  {item.label}
                </Link>
              )}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}

/** Kop van de pagina: kruimelpad, titel en ondertitel links, knoppen rechts. */
export function ProfielHeader({
  crumbs,
  title,
  subtitle,
  actions,
}: {
  crumbs: Crumb[]
  title: React.ReactNode
  subtitle: React.ReactNode
  actions: React.ReactNode
}) {
  return (
    <header className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
      <div className="min-w-0 space-y-2">
        <Breadcrumb items={crumbs} />
        <h1 className="text-2xl font-bold tracking-tight break-words sm:text-[28px]">{title}</h1>
        <p className="text-[13px] text-muted-foreground">{subtitle}</p>
      </div>
      <div className="flex flex-wrap items-center gap-2">{actions}</div>
    </header>
  )
}

/** "Aanvullen vanuit website (AI)": nog niet beschikbaar. */
export function AiFillButton() {
  return (
    <>
      <Pill>Binnenkort</Pill>
      <Button variant="outline" disabled title="Binnenkort">
        <Sparkles aria-hidden="true" />
        Aanvullen vanuit website (AI)
      </Button>
    </>
  )
}

/** Aanduiding naast de opslaanknop. */
export function UnsavedNotice() {
  return <span className="text-[13px] text-amber-700 dark:text-amber-400">Niet-opgeslagen wijzigingen</span>
}

// --- Kaarten ----------------------------------------------------------------------------------

/** Alle profielkaarten: twee kolommen zoals het ontwerp, daaronder "Traject & afspraken". */
export function ProfielKaarten({
  form,
  update,
  openCards,
  toggleCard,
  disabled,
  categoryName,
  connections,
}: {
  form: ProfielForm
  update: UpdateField
  openCards: ReadonlySet<CardId>
  toggleCard: (card: CardId) => void
  disabled: boolean
  /** Naam van de gekozen categorie voor de leesweergave; null = geen categorie. */
  categoryName: string | null
  /** Kaart "Koppelingen voor deze klant" onderaan de rechterkolom. */
  connections: React.ReactNode
}) {
  const cardProps = (card: CardId) => ({
    form,
    update,
    editing: openCards.has(card),
    onToggle: () => toggleCard(card),
    disabled,
  })

  return (
    <>
      <div className="grid items-start gap-6 xl:grid-cols-2">
        <div className="flex min-w-0 flex-col gap-6">
          <BedrijfCard {...cardProps("bedrijf")} />
          <DienstenCard {...cardProps("diensten")} />
          <UspsCard {...cardProps("usps")} />
          <BewijsCard {...cardProps("bewijs")} />
        </div>
        <div className="flex min-w-0 flex-col gap-6">
          <ToneCard {...cardProps("tone")} />
          <RegelsCard {...cardProps("regels")} />
          {connections}
        </div>
      </div>

      <TrajectCard {...cardProps("traject")} categoryName={categoryName} />
    </>
  )
}
