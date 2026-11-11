"use client"

import { ChevronDown, ExternalLink, Loader2, Pencil, Sparkles, X } from "lucide-react"
import { useCallback, useEffect, useMemo, useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { AutoStatusBadge, Pill } from "@/components/livegang/shared"
import { SuggestionRow } from "@/components/livegang/SuggestionRow"
import {
  ANALYSIS_STATUS_LABELS,
  apiFetch,
  formatCount,
  formatDateTime,
  INTENTS,
  KEYWORD_SOURCE_LABELS,
  PAGE_TYPE_LABELS,
  updatePageKeyword,
  type AnalysisStatus,
  type AutoStatus,
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

const STATUS_STRIPE: Record<AutoStatus, string> = {
  error: "border-l-red-500",
  warning: "border-l-amber-500",
  ok: "border-l-green-500",
  info: "border-l-blue-500",
  nvt: "border-l-muted-foreground/30",
  unknown: "border-l-muted-foreground/30",
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

/** Compacte AI-status + open voorstellen voor de paginalijst. */
function PageAiStatus({ page }: { page: ContentPage }) {
  if (page.analysis_status === "running" || page.analysis_status === "queued")
    return <Loader2 className="size-3 shrink-0 animate-spin text-blue-600" aria-label="Analyse loopt" />
  if (page.analysis_status === "failed") return <span className="shrink-0 text-red-700">mislukt</span>
  if (page.analysis_status !== "done") return null
  return (
    <span className="shrink-0">
      {page.suggestions_open > 0 ? (
        <span className="font-medium text-blue-700 dark:text-blue-400">{page.suggestions_open} open</span>
      ) : (
        <span className="text-green-700 dark:text-green-400">✓ klaar</span>
      )}
    </span>
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

  const ranking = detail.ahrefs_keyword

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
              {ranking && ranking.keyword === detail.focus_keyword && (
                <span className="text-xs text-muted-foreground">
                  positie {ranking.position ?? "—"} · volume {formatCount(ranking.volume)}
                </span>
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
        {ranking && ranking.keyword !== detail.focus_keyword && (
          <p className="text-xs text-muted-foreground">
            Ahrefs: de pagina krijgt nu het meeste verkeer via &ldquo;{ranking.keyword}&rdquo; (positie{" "}
            {ranking.position ?? "—"}, volume {formatCount(ranking.volume)}).
          </p>
        )}
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
            Terug naar automatisch
          </Button>
        )}
      </div>
      {error && <p className="text-xs text-red-700">{error}</p>}
    </form>
  )
}

/** Paneelinhoud van een pagina: bevindingen van de regelcontrole + AI-voorstellen per checklistpunt. */
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

  if (error) return <p className="px-5 py-4 text-sm text-red-700">{error}</p>
  if (!detail) return <p className="px-5 py-4 text-sm text-muted-foreground">Pagina laden…</p>

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

  function renderItem(key: string) {
    const check = detail!.checks[key]
    const suggestions = detail!.suggestions.filter((s) => s.item_key === key)
    const openCount = suggestions.filter((s) => s.status === "open").length
    return (
      <li key={key}>
        {/* Kopbalk per actiepunt; de streep links volgt de status. */}
        <div className={cn("flex items-start gap-3 border-y border-l-4 bg-muted/50 px-5 py-2.5", STATUS_STRIPE[check.status])}>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold">{itemLabels[key]}</p>
            {check.message && <p className="text-xs text-muted-foreground">{check.message}</p>}
          </div>
          <span className="flex shrink-0 items-center gap-1.5">
            {suggestions.length > 0 && (
              <Pill tone={openCount ? "blue" : "green"}>
                {openCount ? `${openCount} ${openCount === 1 ? "voorstel" : "voorstellen"}` : "Afgehandeld"}
              </Pill>
            )}
            <AutoStatusBadge status={check.status} />
          </span>
        </div>
        {suggestions.length > 0 ? (
          <ul className="divide-y divide-dashed px-5 pb-2">
            {suggestions.map((s) => (
              <SuggestionRow
                key={s.id}
                flat
                suggestion={s}
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
          needsWork(key) && (
            <p className="px-5 py-3 text-xs text-muted-foreground">
              {detail!.analysis_status === "done"
                ? "Geen AI-voorstellen voor dit punt."
                : "Nog geen AI-voorstellen: selecteer deze pagina en start de analyse."}
            </p>
          )
        )}
      </li>
    )
  }

  return (
    <div className="divide-y">
      <section className="px-5 py-4">
        <dl className="grid gap-x-6 gap-y-1.5 text-sm sm:grid-cols-[auto_1fr]">
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
          <dd className="text-xs text-muted-foreground sm:pt-0.5">
            {detail.word_count ?? 0} woorden · {detail.images_total} afbeeldingen · {detail.links_total} interne links
            {detail.analyzed_at ? ` · geanalyseerd ${formatDateTime(detail.analyzed_at)}` : ""}
          </dd>
        </dl>
        {detail.analysis_error && <p className="mt-2 text-xs text-red-700">AI-analyse: {detail.analysis_error}</p>}
      </section>

      <section className="pt-4">
        <p className="px-5 pb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Actiepunten ({todo.length})
        </p>
        {todo.length > 0 ? (
          <ul className="space-y-4 pb-4">{todo.map(renderItem)}</ul>
        ) : (
          <p className="px-5 pb-4 text-sm text-muted-foreground">Geen verbeterpunten of voorstellen voor deze pagina.</p>
        )}
      </section>

      {fine.length > 0 && (
        <section className="px-5 py-3">
          <button
            type="button"
            onClick={() => setShowFine(!showFine)}
            className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
          >
            <ChevronDown className={cn("size-3.5 transition-transform", (showFine || focusKey) && "rotate-180")} />
            {fine.length} {fine.length === 1 ? "punt" : "punten"} zonder verbeterpunt
          </button>
          {(showFine || focusKey) && <ul className="-mx-5 mt-3 space-y-2">{fine.map(renderItem)}</ul>}
        </section>
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

  // Rechts staat altijd een pagina: de aangeklikte, anders de eerste uit de lijst.
  const openPage = visible.find((p) => p.id === open) ?? visible[0] ?? null

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

      <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
        {/* Links: pagina's als tabs */}
        <aside className="overflow-hidden rounded-lg border bg-card lg:sticky lg:top-4 lg:self-start">
          <label className="flex items-center gap-2 border-b px-3 py-2 text-xs text-muted-foreground">
            <input
              type="checkbox"
              checked={allVisibleSelected}
              onChange={toggleVisible}
              aria-label="Selecteer zichtbare pagina's"
            />
            {selected.size > 0 ? `${selected.size} geselecteerd voor analyse` : `${visible.length} pagina's`}
          </label>
          {visible.length === 0 ? (
            <p className="px-3 py-6 text-center text-sm text-muted-foreground">Geen pagina&apos;s voor dit filter.</p>
          ) : (
            <ul className="max-h-[70vh] divide-y overflow-y-auto">
              {visible.map((page) => {
                const active = openPage?.id === page.id
                return (
                  <li
                    key={page.id}
                    className={cn(
                      "flex items-start gap-2 border-l-2 px-3 py-2",
                      active ? "border-l-primary bg-primary/10" : "border-l-transparent hover:bg-muted/50"
                    )}
                  >
                    <input
                      type="checkbox"
                      className="mt-1"
                      checked={selected.has(page.id)}
                      onChange={() => toggle(page.id)}
                      aria-label={`Selecteer ${page.path}`}
                    />
                    <button type="button" className="min-w-0 flex-1 text-left" onClick={() => setOpen(page.id)}>
                      <span className="flex items-center gap-2">
                        <span className={cn("min-w-0 flex-1 truncate text-sm", active && "font-medium")}>{page.path}</span>
                        <span
                          title={`${page.problem_count} problemen`}
                          className={cn(
                            "size-2 shrink-0 rounded-full",
                            page.problem_count >= 4 ? "bg-red-500" : page.problem_count > 0 ? "bg-amber-500" : "bg-green-500"
                          )}
                        />
                        <span className="w-4 shrink-0 text-right text-xs text-muted-foreground">{page.problem_count}</span>
                      </span>
                      <span className="flex items-center gap-2 text-xs text-muted-foreground">
                        <span className="min-w-0 flex-1 truncate">{page.title || "Geen meta titel"}</span>
                        <PageAiStatus page={page} />
                      </span>
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </aside>

        {/* Rechts: alle punten van de gekozen pagina */}
        <section className="min-w-0 overflow-hidden rounded-lg border bg-card">
          {openPage ? (
            <>
              <header className="space-y-1 border-b px-5 py-4">
                <h3 className="truncate font-semibold">{openPage.path}</h3>
                <p className="truncate text-sm text-muted-foreground">{openPage.title || "Geen meta titel"}</p>
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <AnalysisBadge status={openPage.analysis_status} />
                  <span>{PAGE_TYPE_LABELS[openPage.page_type ?? "overig"] ?? openPage.page_type}</span>
                  <a
                    href={openPage.url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="inline-flex items-center gap-1 text-primary hover:underline"
                  >
                    Open pagina <ExternalLink className="size-3" />
                  </a>
                </div>
              </header>
              <div className="[overflow-wrap:anywhere]">
                <PageDetail
                  key={openPage.id}
                  scanId={scanId}
                  page={openPage}
                  itemLabels={itemLabels}
                  focusKey={itemFilter}
                  onChanged={() => {
                    void load()
                    void onChanged()
                  }}
                />
              </div>
            </>
          ) : (
            <p className="px-5 py-10 text-center text-sm text-muted-foreground">Kies links een pagina.</p>
          )}
        </section>
      </div>
    </div>
  )
}
