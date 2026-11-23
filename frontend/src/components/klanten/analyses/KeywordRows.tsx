"use client"

import { useState } from "react"
import { Plus, X } from "lucide-react"

import { selectClass } from "@/components/klanten/analyses/form-controls"
import {
  createRow,
  CUSTOM_URL,
  formatNumber,
  isLiveError,
  keywordKey,
  NEW_PAGE,
  shortUrl,
  withKeyword,
  type RowErrors,
  type WizardRow,
} from "@/components/klanten/analyses/wizard-model"
import { Pill } from "@/components/livegang/shared"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import type { ProposalKeyword } from "@/lib/competitor-analysis"
import { cn } from "@/lib/utils"

const DATALIST_ID = "wizard-bekende-zoekwoorden"
/** Zoveel gevolgde zoekwoorden staan er standaard in de lijst om aan te klikken. */
const TRACKED_PREVIEW = 8

const gridCols = "sm:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)_4.5rem_2.25rem]"

function knownLabel(item: ProposalKeyword) {
  return [
    item.position ? `#${item.position}` : "nog niet rankend",
    item.volume != null ? `${formatNumber(item.volume)} zoekopdrachten/mnd` : null,
  ]
    .filter(Boolean)
    .join(" · ")
}

function PositionBadge({ keyword, known }: { keyword: string; known: ProposalKeyword | undefined }) {
  if (!keywordKey(keyword)) return <span className="text-xs text-muted-foreground">—</span>
  if (known?.position) {
    return (
      <Pill tone={known.position <= 10 ? "green" : "muted"} className="text-xs">
        #{known.position}
      </Pill>
    )
  }
  return (
    <Pill tone="blue" className="text-xs">
      nieuw
    </Pill>
  )
}

function FieldError({ id, message }: { id: string; message: string | undefined }) {
  if (!message) return null
  return (
    <p id={id} className="mt-1 text-xs text-red-700 dark:text-red-300">
      {message}
    </p>
  )
}

/**
 * Kaart "Zoekwoorden & doelpagina's": per rij een zoekwoord (met suggesties uit het voorstel),
 * een doelpagina en de huidige positie, plus de lijst "Gevolgde zoekwoorden" om aan te klikken.
 */
export function KeywordRows({
  rows,
  onRowsChange,
  known,
  proposalKeywords,
  pages,
  maxKeywords,
  host,
  errors,
  formError,
  showErrors,
}: {
  rows: WizardRow[]
  onRowsChange: React.Dispatch<React.SetStateAction<WizardRow[]>>
  known: Map<string, ProposalKeyword>
  /** In de volgorde van het voorstel (hoogste volume eerst). */
  proposalKeywords: ProposalKeyword[]
  /** Rankende URL's van de klant voor de keuzelijst. */
  pages: string[]
  maxKeywords: number
  /** Host van de klant zonder `www.`; leeg = "Andere URL…" kan niet. */
  host: string
  errors: Record<string, RowErrors>
  formError: string | null
  /** Na een poging om te starten: alle meldingen tonen. */
  showErrors: boolean
}) {
  const [showAllTracked, setShowAllTracked] = useState(false)

  const usedKeys = new Set(rows.map((row) => keywordKey(row.keyword)).filter(Boolean))
  const tracked = proposalKeywords.filter((item) => !usedKeys.has(keywordKey(item.keyword)))
  const shownTracked = showAllTracked ? tracked : tracked.slice(0, TRACKED_PREVIEW)
  const hasEmptyRow = rows.some((row) => !keywordKey(row.keyword))
  const atMax = rows.length >= maxKeywords

  function update(id: string, change: (row: WizardRow) => WizardRow) {
    onRowsChange((current) => current.map((row) => (row.id === id ? change(row) : row)))
  }

  function remove(id: string) {
    onRowsChange((current) => {
      const next = current.filter((row) => row.id !== id)
      return next.length > 0 ? next : [createRow("", known)]
    })
  }

  function add() {
    onRowsChange((current) => (current.length >= maxKeywords ? current : [...current, createRow("", known)]))
  }

  /** Een gevolgd zoekwoord vult de eerste lege rij, of komt er als nieuwe rij bij. */
  function pick(keyword: string) {
    onRowsChange((current) => {
      const empty = current.find((row) => !keywordKey(row.keyword))
      if (empty) return current.map((row) => (row.id === empty.id ? withKeyword(row, keyword, known) : row))
      if (current.length >= maxKeywords) return current
      return [...current, createRow(keyword, known)]
    })
  }

  return (
    <section aria-labelledby="wizard-keywords-title" className="flex flex-col gap-4 rounded-xl border bg-card px-6 py-5">
      <div className="space-y-1">
        <h2 id="wizard-keywords-title" className="text-base font-semibold">
          Zoekwoorden &amp; doelpagina&apos;s
        </h2>
        <p className="text-sm text-muted-foreground">
          Doelpagina&apos;s zijn voorgevuld met de rankende URL uit Pro Rank Tracker. Pas aan als een andere pagina
          moet gaan ranken.
        </p>
      </div>

      <datalist id={DATALIST_ID}>
        {proposalKeywords.map((item) => (
          <option key={item.keyword} value={item.keyword} label={knownLabel(item)} />
        ))}
      </datalist>

      <div>
        <div
          aria-hidden
          className={cn(
            "hidden gap-3 border-b pb-2 text-xs font-medium tracking-wide text-muted-foreground uppercase sm:grid",
            gridCols
          )}
        >
          <span>Zoekwoord</span>
          <span>Doelpagina klant</span>
          <span>Positie</span>
          <span />
        </div>

        <ul className="divide-y">
          {rows.map((row, index) => {
            const key = keywordKey(row.keyword)
            const match = key ? known.get(key) : undefined
            const rowErrors = errors[row.id] ?? {}
            const keywordError =
              rowErrors.keyword && (showErrors || isLiveError(rowErrors.keyword)) ? rowErrors.keyword : undefined
            const urlError = showErrors ? rowErrors.url : undefined
            const label = row.keyword.trim() || `rij ${index + 1}`
            const ids = {
              keyword: `wizard-kw-${row.id}`,
              target: `wizard-target-${row.id}`,
              url: `wizard-url-${row.id}`,
            }

            const options = [...pages]
            if (match?.url && !options.includes(match.url)) options.unshift(match.url)
            if (row.target !== NEW_PAGE && row.target !== CUSTOM_URL && !options.includes(row.target)) {
              options.unshift(row.target)
            }
            const rankingElsewhere = match?.url && row.target !== match.url ? shortUrl(match.url) : null

            return (
              <li key={row.id} className={cn("grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-2 py-3 sm:items-start", gridCols)}>
                <div className="col-span-2 sm:col-span-1">
                  <label htmlFor={ids.keyword} className="mb-1 block text-xs text-muted-foreground sm:sr-only">
                    Zoekwoord {index + 1}
                  </label>
                  <Input
                    id={ids.keyword}
                    value={row.keyword}
                    list={DATALIST_ID}
                    autoComplete="off"
                    placeholder="Typ of kies een zoekwoord"
                    onChange={(event) => {
                      const value = event.target.value
                      update(row.id, (current) => withKeyword(current, value, known))
                    }}
                    aria-invalid={keywordError ? true : undefined}
                    aria-describedby={keywordError ? `${ids.keyword}-error` : undefined}
                  />
                  <FieldError id={`${ids.keyword}-error`} message={keywordError} />
                </div>

                <div className="col-span-2 sm:col-span-1">
                  <label htmlFor={ids.target} className="mb-1 block text-xs text-muted-foreground sm:sr-only">
                    Doelpagina voor {label}
                  </label>
                  <select
                    id={ids.target}
                    className={selectClass}
                    value={row.target}
                    onChange={(event) => {
                      const value = event.target.value
                      update(row.id, (current) => ({ ...current, target: value, targetTouched: true }))
                    }}
                    aria-describedby={rankingElsewhere ? `${ids.target}-hint` : undefined}
                  >
                    {options.map((url) => (
                      <option key={url} value={url}>
                        {shortUrl(url)}
                        {url === match?.url ? " (rankt nu)" : ""}
                      </option>
                    ))}
                    <option value={NEW_PAGE}>+ Nieuwe pagina (nog geen ranking)</option>
                    <option value={CUSTOM_URL} disabled={!host}>
                      {host ? "Andere URL…" : "Andere URL… (klant heeft geen website-adres)"}
                    </option>
                  </select>
                  {rankingElsewhere && (
                    <p id={`${ids.target}-hint`} className="mt-1 truncate text-xs text-muted-foreground" title={match?.url ?? undefined}>
                      Nu rankt {rankingElsewhere}
                    </p>
                  )}
                  {row.target === CUSTOM_URL && (
                    <div className="mt-2">
                      <label htmlFor={ids.url} className="sr-only">
                        Andere URL voor {label}
                      </label>
                      <Input
                        id={ids.url}
                        value={row.customUrl}
                        inputMode="url"
                        autoComplete="off"
                        placeholder={host ? `${host}/pagina of /pagina` : "https://"}
                        onChange={(event) => {
                          const value = event.target.value
                          update(row.id, (current) => ({ ...current, customUrl: value }))
                        }}
                        aria-invalid={urlError ? true : undefined}
                        aria-describedby={urlError ? `${ids.url}-error` : undefined}
                      />
                      <FieldError id={`${ids.url}-error`} message={urlError} />
                    </div>
                  )}
                </div>

                <div className="flex items-center gap-2 sm:h-9">
                  <span className="text-xs text-muted-foreground sm:sr-only">Positie</span>
                  <PositionBadge keyword={row.keyword} known={match} />
                </div>

                <div className="flex justify-end sm:h-9 sm:items-center">
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    onClick={() => remove(row.id)}
                    disabled={rows.length === 1 && !key && row.target === NEW_PAGE}
                    aria-label={`Verwijder ${row.keyword.trim() ? `"${row.keyword.trim()}"` : `rij ${index + 1}`}`}
                    title="Verwijderen"
                  >
                    <X />
                  </Button>
                </div>
              </li>
            )
          })}
        </ul>

        <div className="flex flex-wrap items-center gap-3 border-t pt-3">
          <Button type="button" variant="outline" size="sm" onClick={add} disabled={atMax}>
            <Plus />
            Zoekwoord toevoegen
          </Button>
          <span className="text-xs text-muted-foreground">
            {rows.length} van maximaal {maxKeywords}
          </span>
        </div>
        {formError && (
          <p role="alert" className="mt-2 text-sm text-red-700 dark:text-red-300">
            {formError}
          </p>
        )}
      </div>

      <div className="space-y-2 rounded-lg bg-muted/40 px-4 py-3">
        <h3 id="wizard-tracked-title" className="text-sm font-semibold">
          Gevolgde zoekwoorden
        </h3>
        {proposalKeywords.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Er zijn nog geen gevolgde zoekwoorden voor deze klant. Typ zelf een zoekwoord hierboven.
          </p>
        ) : tracked.length === 0 ? (
          <p className="text-sm text-muted-foreground">Alle gevolgde zoekwoorden staan al in de lijst.</p>
        ) : (
          <>
            <p className="text-xs text-muted-foreground">
              Klik om toe te voegen; positie en zoekvolume per maand staan erbij.
            </p>
            <ul aria-labelledby="wizard-tracked-title" className="flex flex-wrap gap-2">
              {shownTracked.map((item) => (
                <li key={item.keyword}>
                  <button
                    type="button"
                    onClick={() => pick(item.keyword)}
                    disabled={atMax && !hasEmptyRow}
                    aria-label={`Voeg ${item.keyword} toe (${knownLabel(item)})`}
                    className="inline-flex items-center gap-1.5 rounded-full border bg-card px-3 py-1 text-xs shadow-xs transition-colors outline-none hover:bg-muted focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <Plus className="size-3" aria-hidden />
                    <span className="font-medium">{item.keyword}</span>
                    <span className="text-muted-foreground">
                      {item.position ? `#${item.position}` : "—"}
                      {item.volume != null ? ` · ${formatNumber(item.volume)}` : ""}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
            {tracked.length > TRACKED_PREVIEW && (
              <button
                type="button"
                onClick={() => setShowAllTracked((value) => !value)}
                aria-expanded={showAllTracked}
                className="text-xs font-semibold underline-offset-2 hover:underline"
              >
                {showAllTracked ? "Toon minder" : `Toon alle ${tracked.length}`}
              </button>
            )}
            {atMax && !hasEmptyRow && (
              <p className="text-xs text-muted-foreground">
                Het maximum van {maxKeywords} zoekwoorden is bereikt; verwijder eerst een rij.
              </p>
            )}
          </>
        )}
      </div>
    </section>
  )
}
