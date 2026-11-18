"use client"

import { Check, Loader2, RotateCcw, Search, X } from "lucide-react"
import { useId, useMemo, useRef, useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { MAX_SCHEMA_TARGET_TYPES } from "@/lib/launch-checklist"
import SCHEMA_ORG_TYPES from "@/lib/schema-org-types.json"
import { cn } from "@/lib/utils"

/**
 * Gangbare types: wat Google als rich result ondersteunt en wat Rank Math als schema kent. Staan bovenaan
 * zonder zoekterm; de rest van schema.org vind je via zoeken.
 */
export const COMMON_SCHEMA_TYPES = [
  "Article",
  "BlogPosting",
  "NewsArticle",
  "WebPage",
  "WebSite",
  "BreadcrumbList",
  "Organization",
  "LocalBusiness",
  "ProfessionalService",
  "Person",
  "Service",
  "Product",
  "ProductGroup",
  "Offer",
  "Brand",
  "Review",
  "AggregateRating",
  "FAQPage",
  "QAPage",
  "HowTo",
  "Event",
  "JobPosting",
  "Course",
  "Recipe",
  "VideoObject",
  "ImageObject",
  "SoftwareApplication",
  "ItemList",
  "CollectionPage",
  "ProfilePage",
  "Book",
  "Dataset",
  "DiscussionForumPosting",
  "EmployerAggregateRating",
  "MerchantReturnPolicy",
  "Restaurant",
]

const ALL_TYPES: string[] = SCHEMA_ORG_TYPES
const ALL_TYPES_LOWER = ALL_TYPES.map((t) => t.toLowerCase())
const MAX_RESULTS = 50

/** Treffers op een deel van de naam (hoofdletterongevoelig); namen die met de zoekterm beginnen eerst. */
function searchTypes(query: string): { items: string[]; more: number } {
  const q = query.trim().toLowerCase()
  if (!q) return { items: COMMON_SCHEMA_TYPES, more: 0 }
  const starts: string[] = []
  const contains: string[] = []
  ALL_TYPES_LOWER.forEach((name, i) => {
    if (name.startsWith(q)) starts.push(ALL_TYPES[i])
    else if (name.includes(q)) contains.push(ALL_TYPES[i])
  })
  // Een exacte treffer helemaal bovenaan, zodat Enter direct het bedoelde type kiest.
  starts.sort((a, b) => Number(b.toLowerCase() === q) - Number(a.toLowerCase() === q))
  const all = [...starts, ...contains]
  return { items: all.slice(0, MAX_RESULTS), more: Math.max(0, all.length - MAX_RESULTS) }
}

function sameTypes(a: string[], b: string[]) {
  return a.length === b.length && a.every((t, i) => t === b[i])
}

/**
 * Doorzoekbare meerkeuzelijst met schema.org-types voor één pagina of een selectie. Wijzigingen worden pas
 * opgeslagen met "Toepassen" (of direct met "Terug naar automatisch"); sluiten zonder toepassen laat de
 * keuze ongewijzigd.
 */
export function SchemaTypePicker({
  value,
  onApply,
  trigger,
  heading,
  autoHint,
  note,
  disabled,
}: {
  /** Huidige eigen keuze; null = automatisch; undefined = verschillend (selectie met uiteenlopende keuzes). */
  value: string[] | null | undefined
  /** Slaat de keuze op (null = terug naar automatisch). Gooit bij een fout; de melding komt in de lijst. */
  onApply: (types: string[] | null) => Promise<void>
  /** Knop die de lijst opent; moet een ref doorgeven (een `<button>` of `Button`). */
  trigger: React.ReactNode
  heading: string
  /** Grijze toelichting over wat automatisch gemaakt wordt. */
  autoHint?: React.ReactNode
  /** Extra toelichting, bijv. bij een selectie met verschillende keuzes. */
  note?: React.ReactNode
  disabled?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<string[]>([])
  const [query, setQuery] = useState("")
  const [active, setActive] = useState(0)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState<"apply" | "auto" | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLUListElement>(null)
  const listId = useId()
  const optionId = (i: number) => `${listId}-option-${i}`

  const { items, more } = useMemo(() => searchTypes(query), [query])
  const activeIndex = items.length ? Math.min(active, items.length - 1) : -1
  const current = value ?? []
  const changed = !sameTypes(draft, current)

  function changeOpen(next: boolean) {
    if (saving) return
    if (next) {
      // Elke opening begint met de opgeslagen keuze.
      setDraft(value ?? [])
      setQuery("")
      setActive(0)
      setNotice(null)
      setError(null)
    }
    setOpen(next)
  }

  function toggle(type: string) {
    setError(null)
    if (draft.includes(type)) {
      setDraft(draft.filter((t) => t !== type))
      setNotice(null)
      return
    }
    if (draft.length >= MAX_SCHEMA_TARGET_TYPES) {
      setNotice(`Maximaal ${MAX_SCHEMA_TARGET_TYPES} types per pagina; haal er eerst een weg.`)
      return
    }
    setDraft([...draft, type])
    setNotice(null)
  }

  function moveActive(next: number) {
    setActive(next)
    document.getElementById(optionId(next))?.scrollIntoView({ block: "nearest" })
  }

  function onKeyDown(ev: React.KeyboardEvent<HTMLInputElement>) {
    if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
      ev.preventDefault()
      if (!items.length) return
      const delta = ev.key === "ArrowDown" ? 1 : -1
      moveActive((Math.max(activeIndex, 0) + delta + items.length) % items.length)
    } else if (ev.key === "Home" && items.length && !query) {
      ev.preventDefault()
      moveActive(0)
    } else if (ev.key === "End" && items.length && !query) {
      ev.preventDefault()
      moveActive(items.length - 1)
    } else if (ev.key === "Enter") {
      ev.preventDefault()
      if (activeIndex >= 0) toggle(items[activeIndex])
    } else if (ev.key === "Backspace" && !query && draft.length) {
      // Zoals bij chips gebruikelijk: lege zoekbalk + backspace haalt de laatste keuze weg.
      setDraft(draft.slice(0, -1))
      setNotice(null)
    }
  }

  async function save(types: string[] | null) {
    setSaving(types === null ? "auto" : "apply")
    setError(null)
    try {
      await onApply(types)
      setSaving(null)
      setOpen(false)
    } catch (err) {
      setSaving(null)
      setError((err as Error).message)
    }
  }

  return (
    <Popover open={open} onOpenChange={changeOpen}>
      <PopoverTrigger asChild disabled={disabled}>
        {trigger}
      </PopoverTrigger>
      <PopoverContent
        className="w-[22rem] space-y-2 p-3"
        align="start"
        onOpenAutoFocus={(e) => {
          e.preventDefault()
          inputRef.current?.focus()
        }}
        aria-label={heading}
      >
        <p className="text-sm font-medium">{heading}</p>

        <div className="flex min-h-7 flex-wrap items-center gap-1" aria-live="polite">
          {draft.length === 0 ? (
            <span className="text-xs text-muted-foreground">
              {value === null ? "Automatisch: nog geen eigen keuze." : "Geen types gekozen."}
            </span>
          ) : (
            draft.map((t) => (
              <span
                key={t}
                className="inline-flex items-center gap-0.5 rounded-full bg-blue-100 py-0.5 pl-2 pr-0.5 text-[11px] font-medium text-blue-800 dark:bg-blue-900/30 dark:text-blue-300"
              >
                {t}
                <button
                  type="button"
                  onClick={() => toggle(t)}
                  aria-label={`${t} weghalen`}
                  title={`${t} weghalen`}
                  className="rounded-full p-0.5 hover:bg-blue-200 dark:hover:bg-blue-800/50"
                >
                  <X className="size-3" />
                </button>
              </span>
            ))
          )}
        </div>

        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            ref={inputRef}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value)
              setActive(0)
              listRef.current?.scrollTo({ top: 0 })
            }}
            onKeyDown={onKeyDown}
            placeholder="Zoek een schema.org-type…"
            className="h-8 pl-8"
            role="combobox"
            aria-label="Zoek een schema.org-type"
            aria-expanded="true"
            aria-controls={listId}
            aria-autocomplete="list"
            aria-activedescendant={activeIndex >= 0 ? optionId(activeIndex) : undefined}
          />
        </div>

        {!query && <p className="text-[11px] text-muted-foreground">Gangbare types; zoek voor alle {ALL_TYPES.length} types van schema.org.</p>}

        <ul
          ref={listRef}
          id={listId}
          role="listbox"
          aria-multiselectable="true"
          aria-label="Schema.org-types"
          className="max-h-60 overflow-y-auto rounded-md border"
        >
          {items.map((t, i) => {
            const chosen = draft.includes(t)
            return (
              <li
                key={t}
                id={optionId(i)}
                role="option"
                aria-selected={chosen}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => toggle(t)}
                onMouseMove={() => activeIndex !== i && setActive(i)}
                className={cn(
                  "flex cursor-pointer items-center gap-2 px-2 py-1 text-sm",
                  i === activeIndex && "bg-muted",
                  chosen && "font-medium"
                )}
              >
                <Check className={cn("size-3.5 shrink-0 text-primary", !chosen && "invisible")} />
                {t}
              </li>
            )
          })}
          {items.length === 0 && <li className="px-2 py-3 text-center text-xs text-muted-foreground">Geen type gevonden.</li>}
          {more > 0 && (
            <li className="border-t px-2 py-1.5 text-center text-[11px] text-muted-foreground" aria-hidden>
              Nog {more}, verfijn je zoekopdracht.
            </li>
          )}
        </ul>

        {notice && <p className="text-xs text-amber-700 dark:text-amber-400">{notice}</p>}
        {autoHint && <div className="text-xs text-muted-foreground">{autoHint}</div>}
        {note && <div className="text-xs text-muted-foreground">{note}</div>}
        {error && <p className="text-xs text-red-700 dark:text-red-400">{error}</p>}

        <div className="flex flex-wrap items-center gap-2 pt-1">
          <Button
            size="sm"
            variant="ghost"
            className="h-7 px-2"
            disabled={saving !== null}
            onClick={() => void save(null)}
            title="Eigen keuze wissen; de types volgen weer uit het paginatype"
          >
            {saving === "auto" ? <Loader2 className="animate-spin" /> : <RotateCcw />} Terug naar automatisch
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="ml-auto h-7 px-2"
            disabled={saving !== null}
            onClick={() => changeOpen(false)}
          >
            Annuleren
          </Button>
          <Button
            size="sm"
            className="h-7 px-2"
            disabled={saving !== null || draft.length === 0 || !changed}
            onClick={() => void save(draft)}
          >
            {saving === "apply" && <Loader2 className="animate-spin" />} Toepassen
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  )
}
