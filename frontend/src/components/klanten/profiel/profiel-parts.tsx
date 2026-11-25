"use client"

// Bouwstenen voor de kaarten op de pagina Klantprofiel: de kaart met "Bewerken", rijen voor
// lezen en bewerken, lijsten, pills en de lege toestand.

import { useId } from "react"
import { Check, CircleAlert } from "lucide-react"

import { ResultCard } from "@/components/klanten/analyses/result-parts"
import { Pill, type Tone } from "@/components/livegang/shared"
import { fieldClassName } from "@/components/settings/SettingsSection"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"

import { filledLines } from "./profiel-form"

// --- Kaart ------------------------------------------------------------------------------------

/**
 * Kaart met rechtsboven "Bewerken" (in bewerkstand "Klaar"). Zonder inhoud en buiten de
 * bewerkstand staat er een rustige melding met de knop "Invullen".
 */
export function ProfielCard({
  id,
  title,
  description,
  editing,
  onToggle,
  empty = false,
  emptyText,
  className,
  children,
}: {
  id: string
  title: string
  description?: React.ReactNode
  editing: boolean
  onToggle: () => void
  /** Kaart heeft nog geen inhoud. */
  empty?: boolean
  emptyText?: string
  className?: string
  children: React.ReactNode
}) {
  return (
    <ResultCard
      id={`profiel-${id}`}
      title={title}
      description={description}
      className={className}
      aside={
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={editing}
          className="text-[13px] font-semibold whitespace-nowrap text-primary underline-offset-4 hover:underline"
        >
          {editing ? "Klaar" : "Bewerken"}
          <span className="sr-only">: {title}</span>
        </button>
      }
    >
      {!editing && empty ? (
        <EmptyState text={emptyText ?? "Nog niet ingevuld."} onFill={onToggle} label={title} />
      ) : (
        children
      )}
    </ResultCard>
  )
}

/** Lege kaart: korte uitleg en een knop die de kaart in bewerkstand zet. */
export function EmptyState({ text, onFill, label }: { text: string; onFill: () => void; label: string }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
      <p>{text}</p>
      <Button type="button" variant="outline" size="sm" onClick={onFill}>
        Invullen
        <span className="sr-only">: {label}</span>
      </Button>
    </div>
  )
}

// --- Leesweergave -----------------------------------------------------------------------------

/** Gedempte aanduiding voor een leeg veld. */
export function NotFilled() {
  return <span className="font-normal text-muted-foreground">Niet ingevuld</span>
}

/** Rijen label → waarde; op smal scherm staat het label boven de waarde. */
export function Rows({ children }: { children: React.ReactNode }) {
  return <dl className="flex flex-col">{children}</dl>
}

export function Row({ label, children }: { label: string; children: React.ReactNode }) {
  const empty = children === null || children === undefined || children === ""
  return (
    <div className="flex flex-col gap-0.5 border-b py-2.5 last:border-b-0 sm:flex-row sm:gap-4">
      <dt className="text-[13px] text-muted-foreground sm:w-[170px] sm:shrink-0">{label}</dt>
      <dd className="min-w-0 text-[13px] font-medium break-words whitespace-pre-line">
        {empty ? <NotFilled /> : children}
      </dd>
    </div>
  )
}

/** Klein kopje binnen een kaart, bijv. "VOORBEELDTEKSTEN". */
export function SubHeading({ id, children }: { id?: string; children: React.ReactNode }) {
  return (
    <h3 id={id} className="text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">
      {children}
    </h3>
  )
}

const LIST_ICONS = {
  check: <Check className="mt-0.5 size-4 shrink-0 text-green-600 dark:text-green-400" aria-hidden="true" />,
  alert: <CircleAlert className="mt-0.5 size-4 shrink-0 text-red-600 dark:text-red-400" aria-hidden="true" />,
  bullet: (
    <span className="mt-[7px] size-1.5 shrink-0 rounded-full bg-muted-foreground" aria-hidden="true" />
  ),
} as const

/** Lijst zinnen met een groen vinkje, rood uitroepteken of een bolletje ervoor. */
export function ItemList({
  items,
  icon,
  labelledBy,
}: {
  items: string[]
  icon: keyof typeof LIST_ICONS
  labelledBy?: string
}) {
  return (
    <ul aria-labelledby={labelledBy} className="flex flex-col gap-2">
      {items.map((item, index) => (
        <li key={`${index}-${item}`} className="flex gap-2.5 text-[13px] break-words">
          {LIST_ICONS[icon]}
          <span className="min-w-0">{item}</span>
        </li>
      ))}
    </ul>
  )
}

/** Rij pills; `href` maakt er een link van (voorbeeldteksten). */
export function PillList({
  items,
  tone,
  labelledBy,
}: {
  items: { label: string; href?: string; title?: string }[]
  tone: Tone
  labelledBy?: string
}) {
  return (
    <ul aria-labelledby={labelledBy} className="flex flex-wrap gap-1.5">
      {items.map((item, index) => (
        <li key={`${index}-${item.label}`} className="max-w-full min-w-0">
          {item.href ? (
            <a
              href={item.href}
              target="_blank"
              rel="noreferrer noopener"
              title={item.title}
              className="inline-flex max-w-full rounded-full hover:opacity-80"
            >
              <Pill tone={tone} className="max-w-full text-xs">
                <span className="truncate">{item.label}</span>
              </Pill>
            </a>
          ) : (
            <Pill tone={tone} className="max-w-full text-xs">
              <span className="truncate">{item.label}</span>
            </Pill>
          )}
        </li>
      ))}
    </ul>
  )
}

// --- Bewerken ---------------------------------------------------------------------------------

/** Velden onder elkaar, in dezelfde opbouw als de leesrijen. */
export function Fields({ children }: { children: React.ReactNode }) {
  return <div className="flex flex-col gap-3">{children}</div>
}

/** Label links (vaste breedte) en veld rechts; op smal scherm onder elkaar. */
export function FieldRow({
  label,
  help,
  required = false,
  children,
}: {
  label: string
  help?: React.ReactNode
  /** Toont een sterretje achter het label. */
  required?: boolean
  /** Krijgt de id voor het veld en de id van de hulptekst. */
  children: (ids: { id: string; helpId: string | undefined }) => React.ReactNode
}) {
  const id = useId()
  const helpId = help ? `${id}-help` : undefined
  return (
    <div className="flex flex-col gap-1 sm:flex-row sm:gap-4">
      <label htmlFor={id} className="pt-2 text-[13px] text-muted-foreground sm:w-[170px] sm:shrink-0">
        {label}
        {required && (
          <span aria-hidden="true" className="text-destructive">
            {" "}*
          </span>
        )}
      </label>
      <div className="min-w-0 flex-1 space-y-1">
        {children({ id, helpId })}
        {help && (
          <p id={helpId} className="text-xs text-muted-foreground">
            {help}
          </p>
        )}
      </div>
    </div>
  )
}

/** Gewoon tekstveld met een maximale lengte. */
export function TextField({
  label,
  value,
  onChange,
  maxLength,
  placeholder,
  disabled,
  type = "text",
  help,
  required = false,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  maxLength?: number
  placeholder?: string
  disabled?: boolean
  type?: "text" | "url" | "date" | "number"
  help?: React.ReactNode
  required?: boolean
}) {
  return (
    <FieldRow label={label} help={help} required={required}>
      {({ id, helpId }) => (
        <Input
          id={id}
          type={type}
          value={value}
          maxLength={maxLength}
          min={type === "number" ? 0 : undefined}
          placeholder={placeholder}
          disabled={disabled}
          aria-describedby={helpId}
          required={required}
          aria-required={required || undefined}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
    </FieldRow>
  )
}

/** Tekstvak; met `maxItems` is het een lijst met één item per regel (of komma). */
export function TextAreaField({
  label,
  value,
  onChange,
  placeholder,
  disabled,
  help,
  maxLength,
  maxItems,
  maxItemLength,
  splitOnComma = false,
  rows = 4,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  placeholder?: string
  disabled?: boolean
  help?: React.ReactNode
  maxLength?: number
  maxItems?: number
  maxItemLength?: number
  splitOnComma?: boolean
  rows?: number
}) {
  const lines = maxItems ? filledLines(value, splitOnComma) : []
  const tooMany = maxItems !== undefined && lines.length > maxItems
  const tooLong = maxItemLength !== undefined && lines.some((line) => line.length > maxItemLength)
  const warning = [
    tooMany && `Alleen de eerste ${maxItems} worden bewaard.`,
    tooLong && `Langere regels worden afgekapt op ${maxItemLength} tekens.`,
  ]
    .filter(Boolean)
    .join(" ")

  return (
    <FieldRow
      label={label}
      help={
        help || warning ? (
          <>
            {help}
            {warning && (
              <span className="block text-amber-700 dark:text-amber-400">{warning}</span>
            )}
          </>
        ) : undefined
      }
    >
      {({ id, helpId }) => (
        <textarea
          id={id}
          rows={rows}
          value={value}
          maxLength={maxLength}
          placeholder={placeholder}
          disabled={disabled}
          aria-describedby={helpId}
          onChange={(event) => onChange(event.target.value)}
          className={cn(fieldClassName, "min-h-20 resize-y")}
        />
      )}
    </FieldRow>
  )
}
