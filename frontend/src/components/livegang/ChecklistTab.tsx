"use client"

import { ArrowRight, Check, ChevronDown, Circle, ExternalLink, Loader2, Minus, Send } from "lucide-react"
import { useMemo, useState } from "react"

import { Button } from "@/components/ui/button"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { AutoStatusBadge, Pill, ProgressBar } from "@/components/livegang/shared"
import {
  apiFetch,
  describeMondayPush,
  MANUAL_STATUS_LABELS,
  MODE_LABELS,
  periodQuery,
  pushToMonday,
  type ChecklistItem,
  type ChecklistPath,
  type ChecklistSection,
  type ManualStatus,
} from "@/lib/launch-checklist"
import { cn } from "@/lib/utils"

type Filter = "all" | "open" | "problems" | "manual"

/** Verwijzing vanuit een checklistpunt naar de plek waar de details staan (ander tabblad). */
export type ChecklistItemAction = { label: string; onClick: () => void }

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "Alles" },
  { key: "open", label: "Open" },
  { key: "problems", label: "Problemen" },
  { key: "manual", label: "Handmatig" },
]

function matches(item: ChecklistItem, filter: Filter) {
  if (filter === "open") return item.effective === "open"
  if (filter === "problems") return item.effective === "open" && (item.auto?.status === "error" || item.auto?.status === "warning")
  if (filter === "manual") return item.mode !== "auto" && item.effective === "open"
  return true
}

export function EffectiveIcon({ item }: { item: ChecklistItem }) {
  if (item.effective === "done") {
    return (
      <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-green-600 text-white">
        <Check className="size-3.5" />
      </span>
    )
  }
  if (item.effective === "nvt") {
    return (
      <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground">
        <Minus className="size-3.5" />
      </span>
    )
  }
  const bad = item.auto?.status === "error"
  return <Circle className={cn("size-6 shrink-0", bad ? "text-red-500" : "text-muted-foreground/60")} />
}

export function Evidence({ values }: { values: string[] }) {
  if (!values.length) return null
  return (
    <ul className="space-y-0.5 text-xs">
      {values.map((value, index) => {
        const url = value.match(/https?:\/\/\S+/)?.[0]
        if (url) {
          const label = value.replace(url, "").trim()
          return (
            <li key={index} className="flex min-w-0 items-center gap-1">
              {label && <span className="shrink-0 text-muted-foreground">{label}</span>}
              <a href={url} target="_blank" rel="noreferrer noopener" className="inline-flex min-w-0 items-center gap-1 text-primary hover:underline">
                <span className="truncate">{url}</span>
                <ExternalLink className="size-3 shrink-0" />
              </a>
            </li>
          )
        }
        return (
          <li key={index} className="break-words text-muted-foreground">
            {value}
          </li>
        )
      })}
    </ul>
  )
}

function ItemRow({
  item,
  customerId,
  path,
  period,
  action,
  details,
  onSaved,
}: {
  item: ChecklistItem
  customerId: string
  path: ChecklistPath
  period?: string
  action: ChecklistItemAction | null
  details?: React.ReactNode
  onSaved: () => Promise<unknown>
}) {
  const [note, setNote] = useState(item.note ?? "")
  const [savedNote, setSavedNote] = useState(item.note)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Notitieveld laten meelopen als de opgeslagen notitie verandert (na herladen).
  if (savedNote !== item.note) {
    setSavedNote(item.note)
    setNote(item.note ?? "")
  }

  async function pushItem() {
    setSaving(true)
    setError(null)
    try {
      const summary = await pushToMonday({ kind: "checklist", customerId, path, period }, [item.key])
      if (summary.messages.length) setError(summary.messages.join(" "))
      await onSaved()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  async function save(body: { manual_status?: ManualStatus | null; note?: string | null }) {
    setSaving(true)
    setError(null)
    try {
      await apiFetch(`/customers/${customerId}/${path}/${item.key}${periodQuery(period)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
      await onSaved()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const auto = item.auto
  const statusOptions: (ManualStatus | null)[] = ["afgerond", "open", "nvt", null]

  return (
    <Collapsible className="group/item">
      <div className="flex items-start gap-3 px-4 py-3">
        <EffectiveIcon item={item} />
        <CollapsibleTrigger className="min-w-0 flex-1 text-left">
          <div className="flex flex-wrap items-center gap-2">
            <span className={cn("text-sm font-medium", item.effective === "nvt" && "text-muted-foreground line-through")}>{item.label}</span>
            {item.priority === "laag" && <Pill>Lage prioriteit</Pill>}
            {item.priority === "hoog" && <Pill tone="red">Belangrijk</Pill>}
            {item.applies_to === "webshop" && <Pill tone="blue">Webshop</Pill>}
            {item.mode !== "auto" && <Pill tone="blue">{MODE_LABELS[item.mode]}</Pill>}
          </div>
          {auto?.message && <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{auto.message}</p>}
          {item.note && <p className="mt-0.5 line-clamp-1 text-xs italic text-muted-foreground">Notitie: {item.note}</p>}
        </CollapsibleTrigger>
        <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
          {action && (
            <Button size="sm" variant="outline" onClick={action.onClick}>
              {action.label} <ArrowRight />
            </Button>
          )}
          {item.mode !== "manual" && <AutoStatusBadge status={auto?.status} />}
          {item.manual_status && <Pill tone={item.manual_status === "afgerond" ? "green" : "muted"}>{MANUAL_STATUS_LABELS[item.manual_status]}</Pill>}
          {item.external_url && (
            <a
              href={item.external_url}
              target="_blank"
              rel="noreferrer noopener"
              className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
            >
              Monday <ExternalLink className="size-3" />
            </a>
          )}
          <CollapsibleTrigger aria-label="Details">
            <ChevronDown className="size-4 text-muted-foreground transition-transform group-data-[state=open]/item:rotate-180" />
          </CollapsibleTrigger>
        </div>
      </div>
      <CollapsibleContent>
        <div className="space-y-3 border-t bg-muted/30 px-4 py-3 pl-13">
          {item.description && <p className="text-xs text-muted-foreground">{item.description}</p>}
          {auto?.message && <p className="text-sm">{auto.message}</p>}
          {details ?? (auto?.evidence && <Evidence values={auto.evidence} />)}
          {item.f1_issue_types.length > 0 && (
            <p className="text-xs text-muted-foreground">
              Details per pagina staan bij de actiepunten van fase 1 (nulmeting).
            </p>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-muted-foreground">Handmatige status:</span>
            {statusOptions.map((option) => {
              const selected = item.manual_status === option
              return (
                <button
                  key={option ?? "auto"}
                  type="button"
                  disabled={saving || selected}
                  onClick={() => void save({ manual_status: option })}
                  className={cn(
                    "rounded-md border px-2.5 py-1 text-xs transition-colors",
                    selected ? "border-primary bg-primary text-primary-foreground" : "bg-white hover:bg-muted"
                  )}
                >
                  {option ? MANUAL_STATUS_LABELS[option] : item.mode === "manual" ? "Leeg" : "Automatisch"}
                </button>
              )
            })}
          </div>
          <label className="block space-y-1">
            <span className="text-xs text-muted-foreground">Notitie</span>
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              onBlur={() => {
                if ((item.note ?? "") !== note.trim()) void save({ note })
              }}
              rows={2}
              placeholder="Bijv. wat er gecontroleerd is, door wie, of waarom n.v.t."
              className="w-full rounded-md border bg-background px-3 py-2 text-sm"
            />
          </label>
          {!item.external_url && item.effective !== "nvt" && (
            <Button size="sm" variant="outline" disabled={saving} onClick={() => void pushItem()}>
              {saving ? <Loader2 className="animate-spin" /> : <Send />} Doorzetten naar Monday
            </Button>
          )}
          {item.updated_at && (
            <p className="text-[11px] text-muted-foreground">
              Laatst handmatig bijgewerkt:{" "}
              {new Intl.DateTimeFormat("nl-NL", { dateStyle: "medium", timeStyle: "short" }).format(new Date(item.updated_at))}
            </p>
          )}
          {error && <p className="text-xs text-red-700">{error}</p>}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}

export function ChecklistTab({
  checklist,
  customerId,
  path = "checklist",
  period,
  itemAction,
  itemDetails,
  onChanged,
}: {
  checklist: { sections: ChecklistSection[] }
  customerId: string
  /** Fase 2 (standaard), de fase-3 of de fase-4 checklist. */
  path?: ChecklistPath
  /** Fase 4: de ronde waar de handmatige status bij hoort. */
  period?: string
  /** Optioneel: knop per punt die naar de bijbehorende details springt. */
  itemAction?: (item: ChecklistItem) => ChecklistItemAction | null
  /** Optioneel: eigen weergave van de details van een punt (in plaats van de evidence-lijst). */
  itemDetails?: (item: ChecklistItem) => React.ReactNode
  onChanged: () => Promise<unknown>
}) {
  const [filter, setFilter] = useState<Filter>("all")
  const [pushing, setPushing] = useState<string | null>(null)
  const [notice, setNotice] = useState<{ text: string; details: string[]; boardUrl: string | null } | null>(null)

  // Open punten die nog niet in Monday staan.
  const pushable = useMemo(
    () =>
      checklist.sections
        .flatMap((s) => s.items)
        .filter((i) => i.effective === "open" && !i.external_url)
        .map((i) => i.key),
    [checklist]
  )

  async function pushOpenItems() {
    if (!pushable.length) return
    if (!window.confirm(`${pushable.length} open checklistpunten als items naar Monday doorzetten?`)) return
    setNotice(null)
    setPushing(`0 / ${pushable.length}`)
    try {
      const summary = await pushToMonday({ kind: "checklist", customerId, path, period }, pushable, (done, total) =>
        setPushing(`${done} / ${total}`)
      )
      setNotice({ text: describeMondayPush(summary), details: summary.messages, boardUrl: summary.board_url })
      await onChanged()
    } catch (err) {
      setNotice({ text: "Doorzetten naar Monday is mislukt.", details: [(err as Error).message], boardUrl: null })
    } finally {
      setPushing(null)
    }
  }

  const counts = useMemo(() => {
    const all = checklist.sections.flatMap((s) => s.items)
    return Object.fromEntries(FILTERS.map((f) => [f.key, all.filter((i) => matches(i, f.key)).length])) as Record<Filter, number>
  }, [checklist])

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            type="button"
            onClick={() => setFilter(f.key)}
            className={cn(
              "rounded-full border px-3 py-1 text-xs transition-colors",
              filter === f.key ? "border-primary bg-primary font-medium text-primary-foreground" : "bg-white text-muted-foreground hover:bg-muted"
            )}
          >
            {f.label} ({counts[f.key]})
          </button>
        ))}
        <Button
          size="sm"
          variant="secondary"
          className="ml-auto"
          disabled={pushing !== null || pushable.length === 0}
          onClick={() => void pushOpenItems()}
        >
          {pushing ? <Loader2 className="animate-spin" /> : <Send />}
          {pushing ? `Doorzetten… ${pushing}` : `Open punten naar Monday (${pushable.length})`}
        </Button>
      </div>

      {notice && (
        <div className="rounded-md border bg-muted/30 px-3 py-2 text-sm">
          <p>
            {notice.text}{" "}
            {notice.boardUrl && (
              <a href={notice.boardUrl} target="_blank" rel="noreferrer noopener" className="text-primary hover:underline">
                Open het bord
              </a>
            )}
          </p>
          {notice.details.map((detail) => (
            <p key={detail} className="text-xs text-red-700">{detail}</p>
          ))}
        </div>
      )}

      {checklist.sections.map((section) => {
        const items = section.items.filter((i) => matches(i, filter))
        return (
          <Collapsible key={section.key} defaultOpen className="group/section overflow-hidden rounded-lg border bg-card">
            <CollapsibleTrigger className="flex w-full items-center gap-4 px-4 py-3 text-left">
              <div className="min-w-0 flex-1 space-y-1.5">
                <div className="flex items-center justify-between gap-3">
                  <h3 className="font-semibold">{section.label}</h3>
                  <span className="text-xs text-muted-foreground">
                    {section.done} / {section.total}
                  </span>
                </div>
                <ProgressBar value={section.done} max={Math.max(section.total, 1)} />
              </div>
              <ChevronDown className="size-4 text-muted-foreground transition-transform group-data-[state=open]/section:rotate-180" />
            </CollapsibleTrigger>
            <CollapsibleContent>
              {items.length === 0 ? (
                <p className="border-t px-4 py-3 text-sm text-muted-foreground">Geen punten voor dit filter.</p>
              ) : (
                <ul className="divide-y border-t">
                  {items.map((item) => (
                    <li key={item.key}>
                      <ItemRow
                        item={item}
                        customerId={customerId}
                        path={path}
                        period={period}
                        action={itemAction?.(item) ?? null}
                        details={itemDetails?.(item)}
                        onSaved={onChanged}
                      />
                    </li>
                  ))}
                </ul>
              )}
            </CollapsibleContent>
          </Collapsible>
        )
      })}
    </div>
  )
}
