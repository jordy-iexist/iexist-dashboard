"use client"

import { ChevronDown, ExternalLink, Loader2, Pencil, Sparkles, X } from "lucide-react"
import { Fragment, useCallback, useEffect, useMemo, useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { AutoStatusBadge, Pill } from "@/components/livegang/shared"
import { SuggestionRow } from "@/components/livegang/SuggestionRow"
import {
  ANALYSIS_STATUS_LABELS,
  apiFetch,
  formatDateTime,
  INTENTS,
  KEYWORD_SOURCE_LABELS,
  PAGE_TYPE_LABELS,
  updatePageKeyword,
  type AnalysisStatus,
  type ContentPage,
  type ContentPageDetail,
} from "@/lib/launch-checklist"
import { usePolling } from "@/hooks/use-polling"
import { cn } from "@/lib/utils"

type Filter = "all" | "problems" | "not_analysed" | "analysed"

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "Alle" },
  { key: "problems", label: "Met problemen" },
  { key: "not_analysed", label: "Niet geanalyseerd" },
  { key: "analysed", label: "Geanalyseerd" },
]

function matches(page: ContentPage, filter: Filter) {
  if (filter === "problems") return page.problem_count > 0
  if (filter === "analysed") return page.analysis_status === "done"
  if (filter === "not_analysed") return page.analysis_status === "none" || page.analysis_status === "failed"
  return true
}

function hasItem(page: ContentPage, key: string) {
  const status = page.checks[key]?.status
  return status === "error" || status === "warning" || page.suggestion_items.includes(key)
}

function AnalysisBadge({ status }: { status: AnalysisStatus }) {
  if (status === "none") return <span className="text-xs text-muted-foreground">—</span>
  const tone = status === "done" ? "green" : status === "failed" ? "red" : "blue"
  return (
    <Pill tone={tone}>
      {status === "running" && <Loader2 className="mr-1 inline size-3 animate-spin" />}
      {ANALYSIS_STATUS_LABELS[status]}
    </Pill>
  )
}

/** Focuszoekwoord tonen en handmatig wijzigen. */
function KeywordEditor({
  scanId,
  detail,
  onSaved,
}: {
  scanId: string
  detail: ContentPageDetail
  onSaved: (next: ContentPageDetail) => void
}) {
  const [editing, setEditing] = useState(false)
  const [keyword, setKeyword] = useState("")
  const [intent, setIntent] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Voorstellen zijn gemaakt op het zoekwoord van de laatste analyse.
  const [changed, setChanged] = useState(false)

  async function save(value: string) {
    setBusy(true)
    setError(null)
    try {
      onSaved(await updatePageKeyword(scanId, detail.id, value, intent || null))
      setEditing(false)
      setChanged(true)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  if (!editing) {
    return (
      <div className="space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          {detail.focus_keyword ? (
            <>
              <span className="font-medium">{detail.focus_keyword}</span>
              <span className="text-xs text-muted-foreground">({detail.intent ?? "intentie onbekend"})</span>
              {detail.keyword_source && (
                <Pill tone={detail.keyword_source === "ai" ? "muted" : "blue"}>
                  {KEYWORD_SOURCE_LABELS[detail.keyword_source] ?? detail.keyword_source}
                </Pill>
              )}
            </>
          ) : (
            <span className="text-muted-foreground">nog niet bepaald (de AI leidt het af bij de analyse)</span>
          )}
          <Button
            size="sm"
            variant="ghost"
            className="h-7"
            onClick={() => {
              setKeyword(detail.focus_keyword ?? "")
              setIntent(detail.intent ?? "")
              setEditing(true)
            }}
          >
            <Pencil /> {detail.focus_keyword ? "Wijzigen" : "Instellen"}
          </Button>
        </div>
        {changed && detail.analysis_status === "done" && (
          <p className="text-xs text-amber-700 dark:text-amber-400">
            Zoekwoord gewijzigd: analyseer deze pagina opnieuw om de voorstellen hierop te baseren.
          </p>
        )}
      </div>
    )
  }

  return (
    <form
      className="space-y-1"
      onSubmit={(e) => {
        e.preventDefault()
        void save(keyword.trim())
      }}
    >
      <div className="flex flex-wrap items-center gap-2">
        <Input
          autoFocus
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          maxLength={200}
          placeholder="Bijv. dakgoot reinigen utrecht"
          className="h-8 w-64 text-sm"
        />
        <select
          value={intent}
          onChange={(e) => setIntent(e.target.value)}
          className="h-8 rounded-md border bg-background px-2 text-xs"
          aria-label="Zoekintentie"
        >
          <option value="">Intentie: door AI</option>
          {INTENTS.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
        <Button size="sm" type="submit" disabled={busy || !keyword.trim()}>
          {busy && <Loader2 className="animate-spin" />} Opslaan
        </Button>
        <Button size="sm" type="button" variant="ghost" disabled={busy} onClick={() => setEditing(false)}>
          Annuleren
        </Button>
        {detail.keyword_source === "manual" && (
          <Button size="sm" type="button" variant="ghost" disabled={busy} onClick={() => void save("")}>
            Terug naar AI
          </Button>
        )}
      </div>
      {error && <p className="text-xs text-red-700">{error}</p>}
    </form>
  )
}

/** Uitgeklapte pagina: bevindingen van de regelcontrole + AI-voorstellen per checklistpunt. */
function PageDetail({
  scanId,
  page,
  itemLabels,
  focusKey,
  onChanged,
}: {
  scanId: string
  page: ContentPage
  itemLabels: Record<string, string>
  /** Alleen dit checklistpunt tonen (vanuit de checklist aangeklikt). */
  focusKey: string | null
  onChanged: () => void
}) {
  const [detail, setDetail] = useState<ContentPageDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [openKeys, setOpenKeys] = useState<Set<string>>(new Set())
  const [showFine, setShowFine] = useState(false)

  // Opnieuw laden zodra de analyse van deze pagina klaar is.
  useEffect(() => {
    let cancelled = false
    apiFetch<ContentPageDetail>(`/scans/${scanId}/content-pages/${page.id}`)
      .then((data) => {
        if (!cancelled) setDetail(data)
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message)
      })
    return () => {
      cancelled = true
    }
  }, [scanId, page.id, page.analysis_status, page.analyzed_at])

  if (error) return <p className="text-sm text-red-700">{error}</p>
  if (!detail) return <p className="text-sm text-muted-foreground">Pagina laden…</p>

  // Volgorde van de checklist aanhouden; punten die n.v.t. zijn weglaten.
  const keys = Object.keys(itemLabels).filter(
    (key) => detail.checks[key] && detail.checks[key].status !== "nvt" && (!focusKey || key === focusKey)
  )
  const count = (key: string) => detail.suggestions.filter((s) => s.item_key === key).length
  const needsWork = (key: string) =>
    detail.checks[key].status === "error" || detail.checks[key].status === "warning" || count(key) > 0
  // Punten met werk bovenaan; de rest staat ingeklapt onder één regel.
  const todo = keys.filter(needsWork)
  const fine = keys.filter((key) => !needsWork(key))

  function toggle(key: string) {
    setOpenKeys((current) => {
      const next = new Set(current)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  function renderItem(key: string) {
    const check = detail!.checks[key]
    const suggestions = detail!.suggestions.filter((s) => s.item_key === key)
    const openCount = suggestions.filter((s) => s.status === "open").length
    const isOpen = openKeys.has(key) || key === focusKey
    return (
      <li key={key}>
        <button
          type="button"
          onClick={() => toggle(key)}
          aria-expanded={isOpen}
          className="flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-muted/40"
        >
          <span className="w-24 shrink-0">
            <AutoStatusBadge status={check.status} />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-medium">{itemLabels[key]}</span>
            <span className={cn("block text-xs text-muted-foreground", !isOpen && "truncate")}>{check.message}</span>
          </span>
          {suggestions.length > 0 && (
            <Pill tone={openCount ? "blue" : "green"}>
              {openCount ? `${openCount} ${openCount === 1 ? "voorstel" : "voorstellen"}` : "Afgehandeld"}
            </Pill>
          )}
          <ChevronDown className={cn("size-4 shrink-0 text-muted-foreground transition-transform", isOpen && "rotate-180")} />
        </button>
        {isOpen &&
          (suggestions.length > 0 ? (
            <ul className="divide-y border-t bg-background/60 pl-6">
              {suggestions.map((s) => (
                <SuggestionRow
                  key={s.id}
                  suggestion={s}
                  defaultOpen={suggestions.length === 1}
                  onChanged={(next) => {
                    setDetail((current) =>
                      current
                        ? { ...current, suggestions: current.suggestions.map((x) => (x.id === next.id ? next : x)) }
                        : current
                    )
                    onChanged()
                  }}
                />
              ))}
            </ul>
          ) : (
            <p className="border-t px-3 py-2 pl-9 text-xs text-muted-foreground">
              {detail!.analysis_status === "done"
                ? "Geen AI-voorstellen voor dit punt."
                : "Nog geen AI-voorstellen: selecteer deze pagina en start de analyse."}
            </p>
          ))}
      </li>
    )
  }

  return (
    <div className="space-y-3">
      <dl className="grid gap-x-6 gap-y-1 rounded-md border bg-card px-3 py-2 text-sm sm:grid-cols-[auto_1fr]">
        <dt className="text-muted-foreground">Meta titel</dt>
        <dd className="min-w-0 break-words">{detail.title || "—"}</dd>
        <dt className="text-muted-foreground">Meta description</dt>
        <dd className="min-w-0 break-words">{detail.meta_description || "—"}</dd>
        <dt className="text-muted-foreground">Focuszoekwoord</dt>
        <dd>
          <KeywordEditor
            scanId={scanId}
            detail={detail}
            onSaved={(next) => {
              setDetail(next)
              onChanged()
            }}
          />
        </dd>
        {detail.readability && (
          <>
            <dt className="text-muted-foreground">Leesbaarheid</dt>
            <dd>{detail.readability}</dd>
          </>
        )}
        <dt className="text-muted-foreground">Pagina</dt>
        <dd className="text-xs text-muted-foreground">
          {detail.word_count ?? 0} woorden · {detail.images_total} afbeeldingen · {detail.links_total} interne links
          {detail.analyzed_at ? ` · geanalyseerd ${formatDateTime(detail.analyzed_at)}` : ""}
        </dd>
      </dl>
      {detail.analysis_error && <p className="text-xs text-red-700">AI-analyse: {detail.analysis_error}</p>}

      {todo.length > 0 ? (
        <ul className="divide-y overflow-hidden rounded-md border bg-card">{todo.map(renderItem)}</ul>
      ) : (
        <p className="text-sm text-muted-foreground">Geen verbeterpunten of voorstellen voor deze pagina.</p>
      )}

      {fine.length > 0 && (
        <div>
          <button
            type="button"
            onClick={() => setShowFine(!showFine)}
            className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
          >
            <ChevronDown className={cn("size-3.5 transition-transform", showFine && "rotate-180")} />
            {fine.length} {fine.length === 1 ? "punt" : "punten"} zonder verbeterpunt
          </button>
          {showFine && <ul className="mt-2 divide-y overflow-hidden rounded-md border bg-card">{fine.map(renderItem)}</ul>}
        </div>
      )}
    </div>
  )
}

export function ContentPagesTab({
  scanId,
  itemLabels,
  analysing,
  gapAnalysed,
  maxPages,
  refreshKey,
  itemFilter,
  onClearItemFilter,
  onStart,
  onChanged,
}: {
  scanId: string
  /** item_key → label, in de volgorde van de checklist. */
  itemLabels: Record<string, string>
  analysing: boolean
  gapAnalysed: boolean
  maxPages: number
  refreshKey: number
  /** Alleen pagina's met een probleem of open voorstel voor dit checklistpunt. */
  itemFilter: string | null
  onClearItemFilter: () => void
  onStart: (pageIds: string[], runGap: boolean) => Promise<void>
  onChanged: () => Promise<unknown>
}) {
  const [pages, setPages] = useState<ContentPage[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<Filter>("problems")
  const [pageType, setPageType] = useState("")
  const [search, setSearch] = useState("")
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [open, setOpen] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)

  const load = useCallback(async () => {
    const data = await apiFetch<{ items: ContentPage[] }>(`/scans/${scanId}/content-pages`)
    setPages(data.items)
  }, [scanId])

  useEffect(() => {
    load().catch((err: Error) => setError(err.message))
  }, [load, refreshKey])

  // Tijdens de analyse de status per pagina bijhouden.
  usePolling(load, analysing, 4000)

  const types = useMemo(() => [...new Set((pages ?? []).map((p) => p.page_type ?? "overig"))].sort(), [pages])
  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return (pages ?? []).filter(
      (p) =>
        (itemFilter ? hasItem(p, itemFilter) : matches(p, filter)) &&
        (!pageType || (p.page_type ?? "overig") === pageType) &&
        (!needle || p.url.toLowerCase().includes(needle) || (p.title ?? "").toLowerCase().includes(needle))
    )
  }, [pages, filter, itemFilter, pageType, search])
  const counts = useMemo(
    () => Object.fromEntries(FILTERS.map((f) => [f.key, (pages ?? []).filter((p) => matches(p, f.key)).length])) as Record<Filter, number>,
    [pages]
  )

  const tooMany = selected.size > maxPages
  const allVisibleSelected = visible.length > 0 && visible.every((p) => selected.has(p.id))

  function toggle(id: string) {
    setSelected((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function toggleVisible() {
    setSelected((current) => {
      const next = new Set(current)
      if (allVisibleSelected) visible.forEach((p) => next.delete(p.id))
      else visible.slice(0, Math.max(0, maxPages - next.size) || 0).forEach((p) => next.add(p.id))
      return next
    })
  }

  async function start() {
    const ids = [...selected]
    const redo = (pages ?? []).filter((p) => selected.has(p.id) && p.analysis_status === "done").length
    const question =
      `${ids.length} pagina('s) door de AI-agents laten analyseren?` +
      (redo ? `\n\n${redo} daarvan zijn al geanalyseerd: open voorstellen van die pagina's worden vervangen.` : "")
    if (!window.confirm(question)) return
    setStarting(true)
    setError(null)
    try {
      await onStart(ids, !gapAnalysed)
      setSelected(new Set())
      await load()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setStarting(false)
    }
  }

  if (pages === null) {
    return error ? (
      <p className="rounded-md border border-red-300 px-3 py-2 text-sm text-red-700">{error}</p>
    ) : (
      <p className="text-sm text-muted-foreground">Pagina&apos;s laden…</p>
    )
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        De regelcontrole heeft alle pagina&apos;s bekeken. Vink de pagina&apos;s aan die de AI-agents inhoudelijk moeten
        beoordelen (maximaal {maxPages} per keer); per pagina krijg je voorstellen per checklistpunt. Je kunt later
        meer pagina&apos;s laten analyseren zonder opnieuw te scannen.
      </p>

      {itemFilter && (
        <div className="flex flex-wrap items-center gap-2 rounded-md border border-primary/40 bg-primary/5 px-3 py-2 text-sm">
          <span className="min-w-0 flex-1">
            Pagina&apos;s met een verbeterpunt of open voorstel voor: <b>{itemLabels[itemFilter] ?? itemFilter}</b>. Klap
            een pagina uit om de bevinding en de voorstellen te zien.
          </span>
          <Button size="sm" variant="ghost" onClick={onClearItemFilter}>
            <X /> Toon alle punten
          </Button>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            type="button"
            onClick={() => {
              setFilter(f.key)
              onClearItemFilter()
            }}
            className={cn(
              "rounded-full border px-3 py-1 text-xs transition-colors",
              !itemFilter && filter === f.key ? "border-primary bg-primary font-medium text-primary-foreground" : "bg-white text-muted-foreground hover:bg-muted"
            )}
          >
            {f.label} ({counts[f.key]})
          </button>
        ))}
        <select
          value={pageType}
          onChange={(e) => setPageType(e.target.value)}
          className="h-8 rounded-md border bg-background px-2 text-xs"
          aria-label="Paginatype"
        >
          <option value="">Alle paginatypes</option>
          {types.map((t) => (
            <option key={t} value={t}>
              {PAGE_TYPE_LABELS[t] ?? t}
            </option>
          ))}
        </select>
        <Input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Zoek op URL of titel"
          className="h-8 w-48 text-xs"
        />
        <Button
          size="sm"
          className="ml-auto"
          disabled={analysing || starting || selected.size === 0 || tooMany}
          onClick={() => void start()}
          title={tooMany ? `Maximaal ${maxPages} pagina's per analyse` : undefined}
        >
          {analysing || starting ? <Loader2 className="animate-spin" /> : <Sparkles />}
          {analysing ? "Analyse loopt…" : `Analyseer geselecteerde (${selected.size})`}
        </Button>
      </div>
      {tooMany && (
        <p className="text-xs text-red-700">
          Je hebt {selected.size} pagina&apos;s geselecteerd; maximaal {maxPages} per analyse.
        </p>
      )}
      {error && <p className="rounded-md border border-red-300 px-3 py-2 text-sm text-red-700">{error}</p>}

      <div className="overflow-x-auto rounded-lg border bg-card">
        {/* Vaste kolombreedtes: lange teksten kappen af of breken af in plaats van de tabel op te rekken. */}
        <table className="w-full min-w-[760px] table-fixed text-sm">
          <thead className="border-b text-left text-xs text-muted-foreground">
            <tr>
              <th className="w-10 px-3 py-2">
                <input
                  type="checkbox"
                  checked={allVisibleSelected}
                  onChange={toggleVisible}
                  aria-label="Selecteer zichtbare pagina's"
                />
              </th>
              <th className="px-3 py-2 font-medium">Pagina</th>
              <th className="w-36 px-3 py-2 font-medium">Type</th>
              <th className="w-24 px-3 py-2 font-medium">Problemen</th>
              <th className="w-36 px-3 py-2 font-medium">AI-analyse</th>
              <th className="w-28 px-3 py-2 font-medium">Voorstellen</th>
              <th className="w-20 px-3 py-2" />
            </tr>
          </thead>
          <tbody className="divide-y">
            {visible.length === 0 && (
              <tr>
                <td colSpan={7} className="px-3 py-6 text-center text-muted-foreground">
                  Geen pagina&apos;s voor dit filter.
                </td>
              </tr>
            )}
            {visible.map((page) => {
              const isOpen = open === page.id
              return (
                <Fragment key={page.id}>
                  <tr className={cn("align-top", isOpen && "bg-muted/30")}>
                    <td className="px-3 py-2">
                      <input
                        type="checkbox"
                        checked={selected.has(page.id)}
                        onChange={() => toggle(page.id)}
                        aria-label={`Selecteer ${page.path}`}
                      />
                    </td>
                    <td className="px-3 py-2">
                      <button type="button" className="block w-full text-left" onClick={() => setOpen(isOpen ? null : page.id)}>
                        <span className="block truncate font-medium">{page.path}</span>
                        <span className="block truncate text-xs text-muted-foreground">{page.title || "Geen meta titel"}</span>
                      </button>
                    </td>
                    <td className="truncate px-3 py-2 text-xs text-muted-foreground">
                      {PAGE_TYPE_LABELS[page.page_type ?? "overig"] ?? page.page_type}
                    </td>
                    <td className="px-3 py-2">
                      {page.problem_count > 0 ? (
                        <Pill tone={page.problem_count >= 4 ? "red" : "amber"}>{page.problem_count}</Pill>
                      ) : (
                        <Pill tone="green">0</Pill>
                      )}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2">
                      <AnalysisBadge status={page.analysis_status} />
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-xs">
                      {page.suggestions_total > 0 ? (
                        <span>
                          <span className="font-medium">{page.suggestions_open}</span> open
                          <span className="text-muted-foreground"> / {page.suggestions_total}</span>
                        </span>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-2">
                        <a href={page.url} target="_blank" rel="noreferrer noopener" aria-label="Open pagina" className="text-muted-foreground hover:text-foreground">
                          <ExternalLink className="size-4" />
                        </a>
                        <button type="button" aria-label="Details" onClick={() => setOpen(isOpen ? null : page.id)}>
                          <ChevronDown className={cn("size-4 text-muted-foreground transition-transform", isOpen && "rotate-180")} />
                        </button>
                      </div>
                    </td>
                  </tr>
                  {isOpen && (
                    <tr className="bg-muted/30">
                      <td colSpan={7} className="min-w-0 px-4 pb-4 pt-1 [overflow-wrap:anywhere]">
                        <PageDetail
                          scanId={scanId}
                          page={page}
                          itemLabels={itemLabels}
                          focusKey={itemFilter}
                          onChanged={() => {
                            void load()
                            void onChanged()
                          }}
                        />
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
