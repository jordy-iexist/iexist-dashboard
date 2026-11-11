"use client"

import { ChevronLeft, ChevronRight, ExternalLink, Search } from "lucide-react"
import { useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { CwvBadge, HttpStatusBadge, Pill } from "@/components/livegang/shared"
import { apiFetch, type LaunchScanIssue, type LaunchScanPage } from "@/lib/launch-checklist"
import { cn } from "@/lib/utils"

const FILTERS: { value: string; label: string }[] = [
  { value: "", label: "Alle URL's" },
  { value: "indexable", label: "Indexeerbaar" },
  { value: "non_indexable", label: "Niet indexeerbaar" },
  { value: "errors", label: "Fouten" },
  { value: "redirects", label: "Redirects" },
  { value: "missing_title", label: "Zonder title" },
  { value: "missing_meta", label: "Zonder meta" },
  { value: "missing_h1", label: "Zonder H1" },
  { value: "multiple_h1", label: "Meerdere H1" },
]

const PAGE_SIZE = 50

function lengthTone(length: number | null, min: number, max: number) {
  if (length === null || length === 0) return "text-red-600"
  if (length > max || length < min) return "text-amber-600"
  return "text-muted-foreground"
}

export function InventoryTab({ scanId }: { scanId: string }) {
  const [filter, setFilter] = useState("")
  const [search, setSearch] = useState("")
  const [debounced, setDebounced] = useState("")
  const [offset, setOffset] = useState(0)
  const [data, setData] = useState<{ pages: LaunchScanPage[]; total: number } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<LaunchScanPage | null>(null)

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebounced(search)
      setOffset(0)
    }, 300)
    return () => clearTimeout(timer)
  }, [search])

  useEffect(() => {
    const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) })
    if (filter) params.set("filter", filter)
    if (debounced.trim()) params.set("search", debounced.trim())
    let cancelled = false
    apiFetch<{ pages: LaunchScanPage[]; total: number }>(`/scans/${scanId}/pages?${params}`)
      .then((result) => !cancelled && (setData(result), setError(null)))
      .catch((err: Error) => !cancelled && setError(err.message))
    return () => {
      cancelled = true
    }
  }, [scanId, filter, debounced, offset])

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {FILTERS.map((f) => (
          <button
            key={f.value}
            type="button"
            onClick={() => {
              setFilter(f.value)
              setOffset(0)
            }}
            className={cn(
              "rounded-full border px-3 py-1 text-xs transition-colors",
              filter === f.value ? "border-primary bg-primary text-primary-foreground" : "hover:bg-muted"
            )}
          >
            {f.label}
          </button>
        ))}
        <div className="relative ml-auto w-full sm:w-64">
          <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Zoek URL of title…" className="pl-9" />
        </div>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}

      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full min-w-[900px] text-sm">
          <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2 font-medium">URL</th>
              <th className="px-3 py-2 font-medium">Status</th>
              <th className="px-3 py-2 font-medium">Indexeerbaar</th>
              <th className="px-3 py-2 font-medium">Title</th>
              <th className="px-3 py-2 font-medium">Meta</th>
              <th className="px-3 py-2 font-medium">H1</th>
              <th className="px-3 py-2 font-medium">Woorden</th>
              <th className="px-3 py-2 font-medium">CWV</th>
              <th className="px-3 py-2 font-medium">Issues</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {data?.pages.map((page) => (
              <tr key={page.id} onClick={() => setSelected(page)} className="cursor-pointer hover:bg-muted/40">
                <td className="max-w-[280px] px-3 py-2">
                  <p className="truncate font-medium" title={page.url}>{page.path}</p>
                  {page.final_url && page.redirect_chain?.length ? (
                    <p className="truncate text-xs text-muted-foreground">→ {page.final_url}</p>
                  ) : null}
                </td>
                <td className="px-3 py-2"><HttpStatusBadge status={page.status_code} error={page.error} /></td>
                <td className="px-3 py-2">
                  {page.indexable === true ? (
                    <Pill tone="green">Ja</Pill>
                  ) : page.indexable === false ? (
                    <Pill tone="red" className="max-w-[160px] truncate">{page.indexability_reason ?? "Nee"}</Pill>
                  ) : (
                    <span className="text-xs text-muted-foreground">{page.indexability_reason ?? "—"}</span>
                  )}
                </td>
                <td className="max-w-[240px] px-3 py-2">
                  <p className="truncate" title={page.title ?? ""}>{page.title || "—"}</p>
                  {page.indexable && (
                    <p className={cn("text-xs", lengthTone(page.title_length, 30, 60))}>{page.title_length ?? 0} tekens</p>
                  )}
                </td>
                <td className={cn("px-3 py-2 text-xs", page.indexable ? lengthTone(page.meta_description_length, 70, 160) : "text-muted-foreground")}>
                  {page.indexable ? `${page.meta_description_length ?? 0} tekens` : "—"}
                </td>
                <td className={cn("px-3 py-2 text-xs", page.indexable && page.h1_count !== 1 && "font-semibold text-red-600")}>
                  {page.h1_count ?? "—"}
                </td>
                <td className="px-3 py-2 text-xs">{page.word_count ?? "—"}</td>
                <td className="px-3 py-2"><CwvBadge rating={page.cwv_status} /></td>
                <td className="px-3 py-2 text-xs">{page.issue_count || "—"}</td>
              </tr>
            ))}
            {data && data.pages.length === 0 && (
              <tr>
                <td colSpan={9} className="px-3 py-8 text-center text-sm text-muted-foreground">Geen URL&apos;s voor dit filter.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {data && data.total > PAGE_SIZE && (
        <div className="flex items-center justify-end gap-2 text-sm text-muted-foreground">
          <span>
            {offset + 1}–{Math.min(offset + PAGE_SIZE, data.total)} van {data.total}
          </span>
          <Button size="icon-sm" variant="ghost" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
            <ChevronLeft />
          </Button>
          <Button size="icon-sm" variant="ghost" disabled={offset + PAGE_SIZE >= data.total} onClick={() => setOffset(offset + PAGE_SIZE)}>
            <ChevronRight />
          </Button>
        </div>
      )}

      <PageDetailSheet scanId={scanId} page={selected} onClose={() => setSelected(null)} />
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-0.5">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="break-words text-sm">{children}</dd>
    </div>
  )
}

function PageDetailSheet({ scanId, page, onClose }: { scanId: string; page: LaunchScanPage | null; onClose: () => void }) {
  const [issues, setIssues] = useState<LaunchScanIssue[]>([])

  useEffect(() => {
    if (!page) return
    let cancelled = false
    apiFetch<{ issues: LaunchScanIssue[] }>(`/scans/${scanId}/issues?page_id=${page.id}`)
      .then((r) => !cancelled && setIssues(r.issues))
      .catch(() => !cancelled && setIssues([]))
    return () => {
      cancelled = true
    }
  }, [scanId, page])

  const lab = page?.cwv?.lab

  return (
    <Sheet open={page !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
        {page && (
          <>
            <SheetHeader>
              <SheetTitle className="break-all pr-6">{page.path}</SheetTitle>
              <SheetDescription asChild>
                <a href={page.url} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 break-all hover:underline">
                  {page.url} <ExternalLink className="size-3" />
                </a>
              </SheetDescription>
            </SheetHeader>
            <dl className="grid gap-4 px-4 pb-6 sm:grid-cols-2">
              <Field label="Status"><HttpStatusBadge status={page.status_code} error={page.error} /> {page.error}</Field>
              <Field label="Indexeerbaar">{page.indexable === null ? "—" : page.indexable ? "Ja" : `Nee: ${page.indexability_reason}`}</Field>
              <Field label="HTTP-versie / respons">{page.http_version ?? "—"} · {page.response_time_ms ?? "—"} ms · {page.size_bytes ? `${Math.round(page.size_bytes / 1024)} KB` : "—"}</Field>
              <Field label="In sitemap">{page.in_sitemap ? "Ja" : "Nee"}</Field>
              {page.redirect_chain && page.redirect_chain.length > 0 && (
                <Field label="Redirectketen">
                  <ol className="space-y-0.5 text-xs">
                    {page.redirect_chain.map((hop, i) => (
                      <li key={i}>{hop.status} · {hop.url}</li>
                    ))}
                  </ol>
                </Field>
              )}
              <div className="sm:col-span-2"><Field label={`Title (${page.title_length ?? 0})`}>{page.title || "—"}</Field></div>
              <div className="sm:col-span-2"><Field label={`Meta description (${page.meta_description_length ?? 0})`}>{page.meta_description || "—"}</Field></div>
              <div className="sm:col-span-2">
                <Field label={`H1 (${page.h1_count ?? 0})`}>{page.h1?.length ? page.h1.map((h, i) => <p key={i}>• {h || "(leeg)"}</p>) : "—"}</Field>
              </div>
              <Field label="Canonical">{page.canonical || "—"}</Field>
              <Field label="Meta robots">{page.meta_robots || "—"}</Field>
              <Field label="Lang / hreflang">{page.lang || "—"}{page.hreflang?.length ? ` · ${page.hreflang.map((h) => h.lang).join(", ")}` : ""}</Field>
              <Field label="Woorden">{page.word_count ?? "—"}</Field>
              <Field label="Links intern / extern">{page.internal_links ?? "—"} / {page.external_links ?? "—"}</Field>
              <Field label="Afbeeldingen (zonder alt)">{page.images_total ?? "—"} ({page.images_missing_alt ?? 0})</Field>
              <div className="sm:col-span-2"><Field label="Structured data">{page.schema_types?.length ? page.schema_types.join(", ") : "Geen"}</Field></div>
              {page.broken_links && page.broken_links.length > 0 && (
                <div className="sm:col-span-2">
                  <Field label="Kapotte links">
                    <ul className="space-y-0.5 text-xs">
                      {page.broken_links.map((l) => <li key={l.url}>{l.status ?? "fout"} · {l.url}</li>)}
                    </ul>
                  </Field>
                </div>
              )}
              {lab && (
                <div className="sm:col-span-2">
                  <Field label={`Core Web Vitals (mobiel, ${page.cwv?.source === "field" ? "velddata" : "labdata"})`}>
                    <span className="flex flex-wrap items-center gap-2">
                      <CwvBadge rating={page.cwv_status} />
                      Score {lab.performance_score ?? "—"} · LCP {lab.lcp ? (lab.lcp / 1000).toFixed(1) : "—"}s · CLS {lab.cls?.toFixed(2) ?? "—"} · TBT {lab.tbt ? Math.round(lab.tbt) : "—"} ms
                    </span>
                  </Field>
                </div>
              )}
              {issues.length > 0 && (
                <div className="sm:col-span-2">
                  <Field label={`Actiepunten (${issues.length})`}>
                    <ul className="space-y-1">
                      {issues.map((i) => <li key={i.id} className="text-sm">• {i.title}</li>)}
                    </ul>
                  </Field>
                </div>
              )}
            </dl>
          </>
        )}
      </SheetContent>
    </Sheet>
  )
}
