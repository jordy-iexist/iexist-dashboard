"use client"

import { useState } from "react"

import { checkboxClass } from "@/components/klanten/analyses/form-controls"
import { CardMessage, ResultCard, type ResultCardState } from "@/components/klanten/analyses/result-parts"
import { Pill } from "@/components/livegang/shared"
import {
  LEVEL_LABELS,
  MODULES,
  formatAnalysisDate,
  updateAction,
  type ActionItem,
  type Level,
} from "@/lib/competitor-analysis"
import { cn } from "@/lib/utils"

function levelText(level: Level | null) {
  return level ? LEVEL_LABELS[level].toLowerCase() : "onbekend"
}

/**
 * Verbeterpunten met een vinkje. Afvinken slaat direct op: de wijziging staat meteen op het
 * scherm (optimistisch) en wordt teruggedraaid met een melding als opslaan mislukt.
 *
 * `overrides` houdt de laatste eigen wijziging per punt vast, zodat een verversing van het
 * detail die nog van vóór het opslaan is, het vinkje niet terugzet. Het component krijgt een
 * `key` per zoekwoord, zodat dit bij wisselen opnieuw begint.
 */
export function ActionsCard({
  actions,
  state,
  error,
}: {
  actions: ActionItem[]
  state: ResultCardState
  error?: string | null
}) {
  const [overrides, setOverrides] = useState<Record<string, ActionItem>>({})
  const [saving, setSaving] = useState<Record<string, boolean>>({})
  const [saveError, setSaveError] = useState<string | null>(null)

  const items = actions.map((action) => overrides[action.id] ?? action)
  const doneCount = items.filter((item) => item.done).length

  async function toggle(action: ActionItem) {
    const done = !action.done
    const previous = overrides[action.id]
    setSaveError(null)
    setSaving((current) => ({ ...current, [action.id]: true }))
    setOverrides((current) => ({
      ...current,
      [action.id]: { ...action, done, done_by_name: null, done_at: done ? new Date().toISOString() : null },
    }))
    try {
      const saved = await updateAction(action.id, done)
      setOverrides((current) => ({ ...current, [action.id]: saved }))
    } catch (err) {
      setOverrides((current) => {
        const next = { ...current }
        if (previous) next[action.id] = previous
        else delete next[action.id]
        return next
      })
      setSaveError(`“${action.title}” kon niet worden ${done ? "afgevinkt" : "heropend"}: ${(err as Error).message}`)
    } finally {
      setSaving((current) => {
        const next = { ...current }
        delete next[action.id]
        return next
      })
    }
  }

  return (
    <ResultCard
      id="actions"
      title="Verbeterpunten"
      description="Geprioriteerd op verwachte impact × moeite. Vink af wat is opgepakt."
      aside={
        state === "filled" && items.length > 0 ? (
          <span className="text-xs whitespace-nowrap text-muted-foreground">
            {doneCount} van {items.length} opgepakt
          </span>
        ) : undefined
      }
    >
      {saveError && (
        <p role="alert" className="rounded-md border border-red-300 bg-card px-3 py-2 text-sm text-red-700 dark:text-red-300">
          {saveError}
        </p>
      )}
      {state !== "filled" ? (
        <CardMessage
          state={state}
          error={error}
          texts={{
            pending: "De verbeterpunten worden opgesteld zodra de pagina's zijn geanalyseerd…",
            empty: "Er zijn geen verbeterpunten gevonden: de pagina blijft op de geanalyseerde onderdelen niet duidelijk achter bij de concurrenten.",
            not_configured: "Er is geen Claude-sleutel ingesteld (ANTHROPIC_API_KEY), dus de AI-analyse en de verbeterpunten zijn overgeslagen.",
            unavailable: "De AI-analyse is mislukt, dus er zijn geen verbeterpunten opgesteld.",
          }}
        />
      ) : (
        <ul className="divide-y">
          {items.map((item) => {
            const inputId = `action-${item.id}`
            const busy = Boolean(saving[item.id])
            const doneAt = formatAnalysisDate(item.done_at)
            return (
              <li key={item.id} className="flex gap-3 py-3 first:pt-0 last:pb-0">
                <input
                  id={inputId}
                  type="checkbox"
                  checked={item.done}
                  disabled={busy}
                  onChange={() => toggle(item)}
                  aria-describedby={`${inputId}-meta`}
                  className={cn(checkboxClass, "mt-0.5")}
                />
                <div className="min-w-0 flex-1 space-y-1">
                  <label
                    htmlFor={inputId}
                    className={cn("block cursor-pointer text-sm font-semibold", item.done && "text-muted-foreground line-through")}
                  >
                    {item.title}
                  </label>
                  {item.description && <p className="text-[13px] text-muted-foreground">{item.description}</p>}
                  <p id={`${inputId}-meta`} className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
                    <span>
                      Impact {levelText(item.impact)} · moeite {levelText(item.effort)}
                    </span>
                    {item.category && <Pill>{MODULES[item.category].label}</Pill>}
                    {item.done && (
                      <span className="text-green-700 dark:text-green-400">
                        {busy
                          ? "Opslaan…"
                          : ["Opgepakt", item.done_by_name && `door ${item.done_by_name}`, doneAt && `op ${doneAt}`]
                              .filter(Boolean)
                              .join(" ")}
                      </span>
                    )}
                  </p>
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </ResultCard>
  )
}
