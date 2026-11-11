"use client"

import { Search } from "lucide-react"
import { useCallback, useEffect, useMemo, useState } from "react"

import { Input } from "@/components/ui/input"
import { Pill } from "@/components/livegang/shared"
import {
  apiFetch,
  EXPECTED_SCHEMA,
  PAGE_TYPE_LABELS,
  type LaunchScanPage,
} from "@/lib/launch-checklist"
import { cn } from "@/lib/utils"

const SOURCE_LABELS: Record<string, string> = { rule: "regel", ai: "AI", manual: "handmatig" }

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
        <div className="overflow-x-auto rounded-lg border bg-card">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left font-medium">Pagina</th>
                <th className="px-3 py-2 text-left font-medium">Type</th>
                <th className="px-3 py-2 text-right font-medium" title="Klikdiepte vanaf de homepage">Diepte</th>
                <th className="px-3 py-2 text-right font-medium" title="Aantal pagina's dat hiernaar linkt">Inlinks</th>
                <th className="px-3 py-2 text-left font-medium">Schema</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {visible.map((page) => (
                <tr key={page.id} className={cn(!page.indexable && "opacity-60")}>
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
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
