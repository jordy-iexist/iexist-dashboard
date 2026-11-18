"use client"

import { Braces, ListChecks, Search } from "lucide-react"
import { useCallback, useEffect, useMemo, useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { SchemaBulkDialog } from "@/components/livegang/SchemaBulkDialog"
import { SchemaMarkupDialog } from "@/components/livegang/SchemaMarkupDialog"
import { Pill } from "@/components/livegang/shared"
import {
  apiFetch,
  EXPECTED_SCHEMA,
  PAGE_TYPE_LABELS,
  type LaunchScanPage,
  type SchemaMarkupResponse,
} from "@/lib/launch-checklist"
import { cn } from "@/lib/utils"

const SOURCE_LABELS: Record<string, string> = { rule: "regel", ai: "AI", manual: "handmatig" }

/** Maximaal aantal pagina's per bulkronde (grens van het overzicht in de backend). */
const MAX_BULK = 200

function hasSchema(page: LaunchScanPage, expected: string) {
  const types = page.schema_all ?? []
  return expected.split("|").some((t) => types.includes(t))
}

function CoverageCell({ have, total }: { have: number; total: number }) {
  if (!total) return <span className="text-muted-foreground">—</span>
  const pct = Math.round((100 * have) / total)
  const tone = pct === 100 ? "green" : pct >= 50 ? "amber" : "red"
  return (
    <Pill tone={tone}>
      {have}/{total}
    </Pill>
  )
}

export function SchemaTab({
  geoScanId,
  sourceScanId,
  pageTypes,
  onChanged,
}: {
  geoScanId: string
  sourceScanId: string
  pageTypes: Record<string, number>
  onChanged: () => Promise<unknown>
}) {
  const [pages, setPages] = useState<LaunchScanPage[] | null>(null)
  const [total, setTotal] = useState(0)
  const [typeFilter, setTypeFilter] = useState("")
  const [search, setSearch] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState<string | null>(null)
  const [schemaPage, setSchemaPage] = useState<LaunchScanPage | null>(null)
  const [selected, setSelected] = useState<Set<string>>(() => new Set())
  const [selectionNotice, setSelectionNotice] = useState<string | null>(null)
  const [bulkPages, setBulkPages] = useState<LaunchScanPage[] | null>(null)

  const load = useCallback(async () => {
    try {
      const data = await apiFetch<{ pages: LaunchScanPage[]; total: number }>(
        `/scans/${sourceScanId}/pages?filter=classified&limit=500&sort=path`
      )
      setPages(data.pages)
      setTotal(data.total)
    } catch (err) {
      setError((err as Error).message)
    }
  }, [sourceScanId])

  useEffect(() => {
    void load()
  }, [load])

  // Na het maken van schema het icoon direct bijwerken, zonder de lijst te herladen.
  const markSchema = useCallback((pageId: string, generatedAt: string) => {
    setPages((current) => current && current.map((p) => (p.id === pageId ? { ...p, schema_suggestion_at: generatedAt } : p)))
  }, [])

  // Na plaatsen of verwijderen via Rank Math het icoon direct bijwerken.
  const markPlacement = useCallback((pageId: string, placedAt: string | null) => {
    setPages((current) => current && current.map((p) => (p.id === pageId ? { ...p, schema_placed_at: placedAt } : p)))
  }, [])

  // Na elk antwoord met een voorstel (bulkscherm of dialog) voorstel, beoordeling en plaatsing in de rij bijwerken.
  const applyResult = useCallback((pageId: string, result: SchemaMarkupResponse) => {
    const review = result.review_status === "approved" || result.review_status === "rejected" ? result.review_status : null
    setPages(
      (current) =>
        current &&
        current.map((p) =>
          p.id === pageId
            ? {
                ...p,
                schema_suggestion_at: result.nothing_missing ? p.schema_suggestion_at : result.generated_at,
                schema_placed_at: result.placement?.placed_at ?? null,
                schema_review_status: result.nothing_missing ? null : review,
              }
            : p
        )
    )
  }, [])

  const indexable = useMemo(() => (pages ?? []).filter((p) => p.indexable), [pages])

  const matrix = useMemo(() => {
    const rows: { type: string; pages: LaunchScanPage[] }[] = []
    for (const type of Object.keys(PAGE_TYPE_LABELS)) {
      const list = indexable.filter((p) => p.page_type === type)
      if (list.length) rows.push({ type, pages: list })
    }
    return rows
  }, [indexable])

  const columns = useMemo(() => {
    const set = new Set<string>()
    for (const row of matrix) for (const t of EXPECTED_SCHEMA[row.type] ?? []) set.add(t)
    return [...set]
  }, [matrix])

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase()
    return (pages ?? []).filter(
      (p) => (!typeFilter || p.page_type === typeFilter) && (!q || p.url.toLowerCase().includes(q) || (p.title ?? "").toLowerCase().includes(q))
    )
  }, [pages, typeFilter, search])

  // Alleen indexeerbare pagina's zijn selecteerbaar voor schema in bulk.
  const visibleSelectable = useMemo(() => visible.filter((p) => p.indexable), [visible])
  const visibleSelectedCount = visibleSelectable.filter((p) => selected.has(p.id)).length
  const allVisibleSelected = visibleSelectable.length > 0 && visibleSelectedCount === visibleSelectable.length

  function addToSelection(ids: string[]) {
    const next = new Set(selected)
    let skipped = 0
    for (const id of ids) {
      if (next.has(id)) continue
      if (next.size >= MAX_BULK) skipped++
      else next.add(id)
    }
    setSelected(next)
    setSelectionNotice(
      skipped
        ? `Je kunt maximaal ${MAX_BULK} pagina's tegelijk selecteren; ${skipped} pagina's zijn niet toegevoegd. Doe de rest in een volgende ronde.`
        : null
    )
  }

  function toggleSelected(id: string) {
    if (selected.has(id)) {
      const next = new Set(selected)
      next.delete(id)
      setSelected(next)
      setSelectionNotice(null)
    } else {
      addToSelection([id])
    }
  }

  function toggleVisibleSelected() {
    if (allVisibleSelected) {
      const next = new Set(selected)
      for (const p of visibleSelectable) next.delete(p.id)
      setSelected(next)
      setSelectionNotice(null)
    } else {
      addToSelection(visibleSelectable.map((p) => p.id))
    }
  }

  function clearSelection() {
    setSelected(new Set())
    setSelectionNotice(null)
  }

  function openBulk() {
    // In lijstvolgorde; alleen pagina's die (nog) indexeerbaar in de lijst staan.
    const list = (pages ?? []).filter((p) => p.indexable && selected.has(p.id))
    if (list.length) setBulkPages(list)
  }

  async function changeType(page: LaunchScanPage, pageType: string) {
    setSaving(page.id)
    setError(null)
    try {
      await apiFetch(`/scans/${geoScanId}/pages/${page.id}/page-type`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ page_type: pageType }),
      })
      setPages((current) =>
        (current ?? []).map((p) => (p.id === page.id ? { ...p, page_type: pageType, page_type_source: "manual" } : p))
      )
      await onChanged()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSaving(null)
    }
  }

  if (error && !pages) return <p className="rounded-md border border-red-300 px-3 py-2 text-sm text-red-700">{error}</p>
  if (!pages) return <p className="text-sm text-muted-foreground">Pagina&apos;s laden…</p>

  return (
    <div className="space-y-6">
      <section className="space-y-3">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Verwacht schema per paginatype</h3>
        <div className="overflow-x-auto rounded-lg border bg-card">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left font-medium">Paginatype</th>
                <th className="px-3 py-2 text-right font-medium">Pagina&apos;s</th>
                {columns.map((c) => (
                  <th key={c} className="px-3 py-2 text-center font-medium">
                    {c.replace("|", " / ")}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y">
              {matrix.map((row) => (
                <tr key={row.type}>
                  <td className="px-3 py-2">
                    <button
                      type="button"
                      onClick={() => setTypeFilter(row.type)}
                      className="font-medium hover:text-primary hover:underline"
                    >
                      {PAGE_TYPE_LABELS[row.type] ?? row.type}
                    </button>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{row.pages.length}</td>
                  {columns.map((c) => (
                    <td key={c} className="px-3 py-2 text-center">
                      {(EXPECTED_SCHEMA[row.type] ?? []).includes(c) ? (
                        <CoverageCell have={row.pages.filter((p) => hasSchema(p, c)).length} total={row.pages.length} />
                      ) : (
                        <span className="text-muted-foreground/50">·</span>
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-xs text-muted-foreground">
          Indexeerbare pagina&apos;s per type ({Object.values(pageTypes).reduce((a, b) => a + b, 0)} totaal). Organization
          en BreadcrumbList zijn websitebreed; zie de checklist voor de beoordeling. Klopt een paginatype niet? Pas het
          hieronder aan: de checklist wordt direct herberekend en de correctie geldt ook voor volgende scans.
        </p>
      </section>

      <section className="space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative max-w-xs flex-1">
            <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Zoek URL of title…" className="pl-9" />
          </div>
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
            className="h-9 rounded-md border bg-background px-2 text-sm"
          >
            <option value="">Alle paginatypes</option>
            {Object.entries(PAGE_TYPE_LABELS).map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
          <span className="text-xs text-muted-foreground">
            {visible.length} pagina&apos;s{total > pages.length ? ` (eerste ${pages.length} van ${total})` : ""}
          </span>
        </div>
        {error && <p className="text-sm text-red-700">{error}</p>}
        {selected.size > 0 && (
          <div className="flex flex-wrap items-center gap-3 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2 text-sm">
            <span className="font-medium">{selected.size} pagina&apos;s geselecteerd</span>
            <Button size="sm" variant="ghost" className="h-7 px-2" onClick={clearSelection}>
              Selectie wissen
            </Button>
            <Button size="sm" className="ml-auto" onClick={openBulk}>
              <ListChecks /> Schema genereren en controleren
            </Button>
          </div>
        )}
        {selectionNotice && <p className="text-xs text-amber-700 dark:text-amber-400">{selectionNotice}</p>}
        <div className="overflow-x-auto rounded-lg border bg-card">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-xs text-muted-foreground">
              <tr>
                <th className="w-8 px-3 py-2 text-left">
                  <input
                    type="checkbox"
                    checked={allVisibleSelected}
                    ref={(el) => {
                      if (el) el.indeterminate = visibleSelectedCount > 0 && !allVisibleSelected
                    }}
                    disabled={visibleSelectable.length === 0}
                    onChange={toggleVisibleSelected}
                    aria-label="Selecteer alle zichtbare indexeerbare pagina's"
                    title="Selecteer alle zichtbare indexeerbare pagina's"
                  />
                </th>
                <th className="px-3 py-2 text-left font-medium">Pagina</th>
                <th className="px-3 py-2 text-left font-medium">Type</th>
                <th className="px-3 py-2 text-right font-medium" title="Klikdiepte vanaf de homepage">Diepte</th>
                <th className="px-3 py-2 text-right font-medium" title="Aantal pagina's dat hiernaar linkt">Inlinks</th>
                <th className="px-3 py-2 text-left font-medium">Schema</th>
                <th className="px-3 py-2">
                  <span className="sr-only">Acties</span>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {visible.map((page) => (
                <tr key={page.id} className={cn(!page.indexable && "opacity-60", selected.has(page.id) && "bg-primary/5")}>
                  <td className="px-3 py-2">
                    {page.indexable && (
                      <input
                        type="checkbox"
                        checked={selected.has(page.id)}
                        onChange={() => toggleSelected(page.id)}
                        aria-label={`Selecteer ${page.path}`}
                      />
                    )}
                  </td>
                  <td className="max-w-xs px-3 py-2">
                    <a href={page.url} target="_blank" rel="noreferrer noopener" className="block truncate text-primary hover:underline">
                      {page.path}
                    </a>
                    {page.title && <p className="truncate text-xs text-muted-foreground">{page.title}</p>}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-1.5">
                      <select
                        value={page.page_type ?? "overig"}
                        disabled={saving === page.id}
                        onChange={(e) => void changeType(page, e.target.value)}
                        className="h-8 rounded-md border bg-background px-1.5 text-xs"
                      >
                        {Object.entries(PAGE_TYPE_LABELS).map(([key, label]) => (
                          <option key={key} value={key}>
                            {label}
                          </option>
                        ))}
                      </select>
                      {page.page_type_source && (
                        <span className="text-[10px] text-muted-foreground">{SOURCE_LABELS[page.page_type_source]}</span>
                      )}
                    </div>
                  </td>
                  <td
                    className={cn(
                      "px-3 py-2 text-right tabular-nums",
                      (page.click_depth === null || (page.click_depth ?? 0) > 3) && page.indexable && "text-red-700 dark:text-red-400"
                    )}
                  >
                    {page.click_depth ?? "∞"}
                  </td>
                  <td className={cn("px-3 py-2 text-right tabular-nums", page.inlinks === 0 && page.indexable && "text-amber-700 dark:text-amber-400")}>
                    {page.inlinks ?? "—"}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex max-w-sm flex-wrap gap-1">
                      {(page.schema_all ?? [])
                        .filter((t) => !["ListItem", "ImageObject", "EntryPoint", "SearchAction", "ReadAction", "WebPage", "PropertyValue", "GeoCoordinates", "Country", "Place", "PostalAddress", "ContactPoint", "Language"].includes(t))
                        .slice(0, 8)
                        .map((t) => (
                          <Pill key={t}>{t}</Pill>
                        ))}
                      {page.schema_all !== null && page.schema_all.length === 0 && <Pill tone="red">Geen schema</Pill>}
                    </div>
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-right">
                    {page.indexable && page.schema_review_status === "approved" && (
                      <Pill tone="green" className="mr-1 align-middle">
                        <span title="Huidig schemavoorstel is goedgekeurd">Goedgekeurd</span>
                      </Pill>
                    )}
                    {page.indexable && page.schema_review_status === "rejected" && (
                      <Pill tone="red" className="mr-1 align-middle">
                        <span title="Huidig schemavoorstel is afgekeurd">Afgekeurd</span>
                      </Pill>
                    )}
                    {page.indexable && (
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-7 px-2"
                        title={page.schema_placed_at ? "Schema geplaatst" : "Maak schema"}
                        aria-label={page.schema_placed_at ? "Schema geplaatst" : "Maak schema"}
                        onClick={() => setSchemaPage(page)}
                      >
                        <Braces
                          className={cn(
                            page.schema_placed_at
                              ? "text-green-700 dark:text-green-400"
                              : page.schema_suggestion_at && "text-primary"
                          )}
                        />
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      {schemaPage && (
        <SchemaMarkupDialog
          key={schemaPage.id}
          scanId={sourceScanId}
          page={schemaPage}
          onClose={() => setSchemaPage(null)}
          onGenerated={markSchema}
          onPlacementChange={markPlacement}
          onResult={applyResult}
        />
      )}
      {bulkPages && (
        <SchemaBulkDialog
          scanId={sourceScanId}
          pages={bulkPages}
          onClose={() => setBulkPages(null)}
          onResult={applyResult}
        />
      )}
    </div>
  )
}
