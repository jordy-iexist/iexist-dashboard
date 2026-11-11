"use client"

import { ChevronDown, Loader2, Sparkles } from "lucide-react"
import { useCallback, useEffect, useMemo, useState } from "react"

import { Button } from "@/components/ui/button"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Pill } from "@/components/livegang/shared"
import { SuggestionRow } from "@/components/livegang/SuggestionRow"
import { apiFetch, type ContentSuggestion } from "@/lib/launch-checklist"

/** Zoekwoord en URL uit de opzet halen voor de ingeklapte regel. */
function field(text: string, name: string) {
  const match = text.match(new RegExp(`\\*\\*${name}:\\*\\*\\s*(.+)`))
  return match ? match[1].replace(/[*`]/g, "").trim() : null
}

function GapPreview({ suggestion }: { suggestion: ContentSuggestion }) {
  const keyword = field(suggestion.proposed_value, "Zoekwoord")
  const url = field(suggestion.proposed_value, "URL")
  if (!keyword && !url) return null
  return (
    <>
      {keyword && <span>Zoekwoord: {keyword}</span>}
      {keyword && url && <span> · </span>}
      {url && <span className="font-mono">{url}</span>}
    </>
  )
}

/** Voorstellen voor nieuwe content (contentgap-agent), als lijst per checklistpunt. */
export function ContentGapTab({
  scanId,
  analysed,
  analysing,
  refreshKey,
  focusKey,
  onRun,
  onChanged,
}: {
  scanId: string
  /** Is de contentgap-analyse al eens gedraaid voor deze scan? */
  analysed: boolean
  analysing: boolean
  refreshKey: number
  /** Checklistpunt dat vanuit de checklist is aangeklikt: komt bovenaan. */
  focusKey: string | null
  onRun: () => Promise<void>
  onChanged: () => Promise<unknown>
}) {
  const [items, setItems] = useState<ContentSuggestion[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)
  const [showHandled, setShowHandled] = useState(false)

  const load = useCallback(async () => {
    const data = await apiFetch<{ items: ContentSuggestion[] }>(`/scans/${scanId}/suggestions?scope=new`)
    setItems(data.items)
  }, [scanId])

  useEffect(() => {
    load().catch((err: Error) => setError(err.message))
  }, [load, refreshKey])

  const handledCount = (items ?? []).filter((s) => s.status !== "open").length
  const groups = useMemo(() => {
    const map = new Map<string, { label: string; items: ContentSuggestion[]; open: number }>()
    for (const s of items ?? []) {
      const group = map.get(s.item_key) ?? { label: s.item_label, items: [], open: 0 }
      group.items.push(s)
      if (s.status === "open") group.open += 1
      map.set(s.item_key, group)
    }
    return [...map.entries()].sort(([a], [b]) => Number(b === focusKey) - Number(a === focusKey))
  }, [items, focusKey])

  async function run() {
    setStarting(true)
    setError(null)
    try {
      await onRun()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setStarting(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <p className="min-w-0 flex-1 text-sm text-muted-foreground">
          Welke landingspagina&apos;s, blogs en overige pagina&apos;s ontbreken nog? Klik een regel open voor de opzet
          (zoekwoord, URL, tussenkoppen en wat de klant moet aanleveren). De inhoud zelf komt van de klant of een expert.
        </p>
        {handledCount > 0 && (
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            <input type="checkbox" checked={showHandled} onChange={(e) => setShowHandled(e.target.checked)} />
            Toon afgehandelde ({handledCount})
          </label>
        )}
        <Button size="sm" variant="secondary" disabled={analysing || starting} onClick={() => void run()}>
          {analysing || starting ? <Loader2 className="animate-spin" /> : <Sparkles />}
          {analysed ? "Opnieuw bepalen" : "Bepaal nieuwe content"}
        </Button>
      </div>
      {error && <p className="rounded-md border border-red-300 px-3 py-2 text-sm text-red-700">{error}</p>}

      {items === null ? (
        <p className="text-sm text-muted-foreground">Voorstellen laden…</p>
      ) : groups.length === 0 ? (
        <p className="rounded-lg border bg-card px-4 py-6 text-center text-sm text-muted-foreground">
          {analysing
            ? "De analyse loopt; voorstellen verschijnen hier zodra ze klaar zijn."
            : analysed
              ? "Geen voorstellen voor nieuwe content."
              : "Nog geen contentgap-analyse gedraaid. Die draait mee met de eerste AI-analyse, of start hem hier los."}
        </p>
      ) : (
        groups.map(([key, group]) => {
          const rows = group.items.filter((s) => showHandled || s.status === "open")
          return (
            <Collapsible key={key} defaultOpen className="group/gap overflow-hidden rounded-lg border bg-card">
              <CollapsibleTrigger className="flex w-full items-center gap-3 px-4 py-3 text-left">
                <h3 className="min-w-0 flex-1 font-semibold">{group.label}</h3>
                <Pill tone={group.open ? "amber" : "green"}>{group.open} open</Pill>
                <span className="text-xs text-muted-foreground">van {group.items.length}</span>
                <ChevronDown className="size-4 text-muted-foreground transition-transform group-data-[state=open]/gap:rotate-180" />
              </CollapsibleTrigger>
              <CollapsibleContent>
                {rows.length === 0 ? (
                  <p className="border-t px-4 py-3 text-sm text-muted-foreground">Alle voorstellen zijn afgehandeld.</p>
                ) : (
                  <ul className="divide-y border-t">
                    {rows.map((s) => (
                      <SuggestionRow
                        key={s.id}
                        suggestion={s}
                        markdown
                        preview={<GapPreview suggestion={s} />}
                        onChanged={(next) => {
                          setItems((current) => current?.map((x) => (x.id === next.id ? next : x)) ?? null)
                          void onChanged()
                        }}
                      />
                    ))}
                  </ul>
                )}
              </CollapsibleContent>
            </Collapsible>
          )
        })
      )}
    </div>
  )
}
