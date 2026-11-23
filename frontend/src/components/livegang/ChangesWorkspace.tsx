"use client"

import { ChevronDown, ExternalLink, Loader2, ScanSearch } from "lucide-react"
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ChangeRow, DoneRow, RejectedRow } from "@/components/livegang/ChangeRow"
import { PanelRow, PhasePanel, Pill } from "@/components/livegang/shared"
import { formatDateTime } from "@/lib/launch-checklist"
import {
  changesHref,
  checkPage,
  fetchPageDetail,
  fetchPages,
  SCHEMA_STATUS_LABELS,
  SiteChangesError,
  type ChangeItem,
  type PageCheckResponse,
  type PageDetail,
  type PagesResponse,
  type PageSummary,
} from "@/lib/site-changes"
import { readUrlParam, writeUrlParams } from "@/lib/url-state"
import { cn } from "@/lib/utils"

// --- doorklikken vanuit andere fases -----------------------------------------

type ChangesNav = { customerId: string; open: (url: string | null) => void }

const ChangesNavContext = createContext<ChangesNav | null>(null)

/** Laat "Bekijk in Aanpassingen"-links binnen de werkruimte van fase wisselen zonder te herladen. */
export function ChangesNavProvider({
  customerId,
  onOpen,
  children,
}: {
  customerId: string
  onOpen: (url: string | null) => void
  children: React.ReactNode
}) {
  const value = useMemo(() => ({ customerId, open: onOpen }), [customerId, onOpen])
  return <ChangesNavContext.Provider value={value}>{children}</ChangesNavContext.Provider>
}

/**
 * Onopvallende link naar het scherm Aanpassingen op één pagina. Binnen de SEO/GEO-werkruimte
 * wisselt een gewone klik direct van fase; nieuw tabblad (Cmd/Ctrl/middelklik) en gebruik
 * buiten de werkruimte volgen de echte URL.
 */
export function ChangesLink({ url, customerId, className }: { url: string; customerId?: string; className?: string }) {
  const nav = useContext(ChangesNavContext)
  const id = nav?.customerId ?? customerId
  if (!id) return null
  return (
    <a
      href={changesHref(id, url)}
      onClick={(e) => {
        if (!nav || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return
        e.preventDefault()
        nav.open(url)
      }}
      className={cn("inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-primary hover:underline", className)}
    >
      Bekijk in Aanpassingen
    </a>
  )
}

// --- scherm ------------------------------------------------------------------

/** Vergelijkingssleutel voor URL's: zonder hash, slash aan het eind en hoofdletters. */
function urlKey(url: string) {
  return url.trim().replace(/#.*$/, "").replace(/\/+$/, "").toLowerCase()
}

function plural(count: number, one: string, many: string) {
  return `${count} ${count === 1 ? one : many}`
}

function checkSummary(result: PageCheckResponse) {
  const parts: string[] = []
  if (result.checked > 0) {
    parts.push(
      `${result.verified} van ${plural(result.checked, "goedgekeurde wijziging", "goedgekeurde wijzigingen")} ${
        result.checked === 1 ? "staat" : "staan"
      } live`
    )
  } else {
    parts.push("Geen goedgekeurde wijzigingen om te controleren")
  }
  parts.push(`${plural(result.resolved_issues, "actiepunt", "actiepunten")} opgelost`)
  return parts.join(", ") + "."
}

/** Item op de plek bijwerken; verwijderen als het naar een andere lijst verhuist. */
function applyLocal(detail: PageDetail, next: ChangeItem): PageDetail {
  const isOpen = next.status === "open" || next.status === "goedgekeurd"
  const replace = (items: ChangeItem[], keep: boolean) =>
    items.flatMap((item) => (item.key === next.key ? (keep ? [next] : []) : [item]))
  return {
    ...detail,
    groups: detail.groups
      .map((group) => ({ ...group, items: replace(group.items, isOpen) }))
      .filter((group) => group.items.length > 0),
    rejected: replace(detail.rejected, next.status === "afgewezen"),
    done: replace(detail.done, next.status === "doorgevoerd"),
  }
}

function PageCounts({ page }: { page: PageSummary }) {
  return (
    <span className="flex shrink-0 flex-wrap justify-end gap-1">
      {page.open_count > 0 && (
        <Pill tone="blue" className="px-1.5">
          <span title="Open">{page.open_count} open</span>
        </Pill>
      )}
      {page.approved_count > 0 && (
        <Pill tone="amber" className="px-1.5">
          <span title="Goedgekeurd, nog niet gedaan">{page.approved_count} goedgek.</span>
        </Pill>
      )}
      {page.done_count > 0 && (
        <Pill tone="green" className="px-1.5">
          <span title="Gedaan">{page.done_count} gedaan</span>
        </Pill>
      )}
    </span>
  )
}

function SchemaLine({ schema }: { schema: NonNullable<PageDetail["schema"]> }) {
  const tone =
    schema.status === "placed" ? "green" : schema.status === "approved" ? "blue" : schema.status === "suggested" ? "amber" : "muted"
  return (
    <div className="flex flex-wrap items-center gap-2 px-5 py-3 text-sm">
      <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Schema</span>
      <Pill tone={tone}>{SCHEMA_STATUS_LABELS[schema.status] ?? schema.status}</Pill>
      {schema.types.length > 0 && <span className="text-muted-foreground">{schema.types.join(", ")}</span>}
      {schema.placed_at && <span className="text-xs text-muted-foreground">geplaatst {formatDateTime(schema.placed_at)}</span>}
      {schema.verified === true && <Pill tone="green">Live teruggezien</Pill>}
      <span className="text-xs text-muted-foreground">· beoordelen en plaatsen gaat via fase 2</span>
    </div>
  )
}

function DetailPanel({
  customerId,
  summary,
  detail,
  error,
  onItemChanged,
  onChecked,
}: {
  customerId: string
  summary: PageSummary | null
  detail: PageDetail | null
  error: SiteChangesError | null
  onItemChanged: (next: ChangeItem) => void
  onChecked: (page: PageDetail) => void
}) {
  const [checking, setChecking] = useState(false)
  const [checkNotice, setCheckNotice] = useState<string | null>(null)
  const [checkError, setCheckError] = useState<string | null>(null)
  const [showRejected, setShowRejected] = useState(false)

  const url = detail?.url ?? summary?.url ?? null

  async function runCheck() {
    if (!url) return
    setChecking(true)
    setCheckNotice(null)
    setCheckError(null)
    try {
      const result = await checkPage(customerId, url)
      onChecked(result.page)
      setCheckNotice(checkSummary(result))
    } catch (err) {
      setCheckError((err as Error).message)
    } finally {
      setChecking(false)
    }
  }

  if (error) {
    return (
      <p className={cn("px-5 py-10 text-center text-sm", error.status === 404 ? "text-muted-foreground" : "text-red-700")}>
        {error.status === 404 ? "Voor deze pagina zijn geen voorstellen of actiepunten gevonden." : error.message}
      </p>
    )
  }
  if (!detail) return <p className="px-5 py-4 text-sm text-muted-foreground">Pagina laden…</p>

  const openCount = detail.groups.reduce((n, g) => n + g.items.length, 0)

  return (
    <>
      <header className="space-y-2 border-b px-5 py-4">
        <div className="flex flex-wrap items-start gap-3">
          <div className="min-w-0 flex-1 space-y-1">
            <h3 className="truncate font-semibold">{detail.path}</h3>
            <p className="truncate text-sm text-muted-foreground">{detail.title || "Geen meta titel"}</p>
          </div>
          <Button size="sm" variant="outline" disabled={checking} onClick={() => void runCheck()}>
            {checking ? <Loader2 className="animate-spin" /> : <ScanSearch />}
            {checking ? "Controleren…" : "Controleer pagina"}
          </Button>
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
          <a
            href={detail.url}
            target="_blank"
            rel="noreferrer noopener"
            className="inline-flex items-center gap-1 text-primary hover:underline"
          >
            Open pagina <ExternalLink className="size-3" />
          </a>
          <span>
            {detail.last_checked_at ? `Laatst gecontroleerd ${formatDateTime(detail.last_checked_at)}` : "Nog niet gecontroleerd"}
          </span>
        </div>
        {checkNotice && (
          <p role="status" className="rounded-md bg-muted/50 px-3 py-2 text-sm">
            {checkNotice}
          </p>
        )}
        {checkError && <p className="text-sm text-red-700">Controleren is mislukt: {checkError}</p>}
      </header>

      <div className="divide-y [overflow-wrap:anywhere]">
        {detail.schema && <SchemaLine schema={detail.schema} />}

        <section className="pt-4">
          <p className="px-5 pb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">Open ({openCount})</p>
          {detail.groups.length > 0 ? (
            <div className="space-y-4 pb-4">
              {detail.groups.map((group) => (
                <div key={group.topic}>
                  <div className="flex items-center gap-2 border-y bg-muted/50 px-5 py-2">
                    <p className="min-w-0 flex-1 text-sm font-semibold">{group.label}</p>
                    <span className="text-xs text-muted-foreground">{group.items.length}</span>
                  </div>
                  <ul className="divide-y divide-dashed px-5">
                    {group.items.map((item) => (
                      <ChangeRow key={item.key} customerId={customerId} item={item} onChanged={onItemChanged} />
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          ) : (
            <p className="px-5 pb-4 text-sm text-muted-foreground">Niets open op deze pagina.</p>
          )}
        </section>

        <section className="px-5 py-4">
          <p className="pb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Gedaan ({detail.done.length})
          </p>
          {detail.done.length > 0 ? (
            <ul className="divide-y divide-dashed">
              {detail.done.map((item) => (
                <DoneRow key={item.key} customerId={customerId} item={item} onChanged={onItemChanged} />
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">Nog niets afgevinkt op deze pagina.</p>
          )}
        </section>

        {detail.rejected.length > 0 && (
          <section className="px-5 py-3">
            <button
              type="button"
              onClick={() => setShowRejected(!showRejected)}
              aria-expanded={showRejected}
              className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
            >
              <ChevronDown className={cn("size-3.5 transition-transform", showRejected && "rotate-180")} />
              Afgewezen ({detail.rejected.length})
            </button>
            {showRejected && (
              <ul className="mt-2 divide-y divide-dashed">
                {detail.rejected.map((item) => (
                  <RejectedRow key={item.key} customerId={customerId} item={item} onChanged={onItemChanged} />
                ))}
              </ul>
            )}
          </section>
        )}
      </div>
    </>
  )
}

export function ChangesWorkspace({ customerId }: { customerId: string }) {
  const [pages, setPages] = useState<PagesResponse | null>(null)
  const [pagesError, setPagesError] = useState<string | null>(null)
  const [search, setSearch] = useState("")
  const [onlyOpen, setOnlyOpen] = useState(true)
  // Gekozen pagina; bij openen uit de URL (?url=), zodat een link naar één pagina deelbaar is.
  const [selectedUrl, setSelectedUrl] = useState<string | null>(() => readUrlParam("url"))
  // Detail en fout horen bij de URL waarvoor ze zijn opgehaald; bij wisselen tonen we niets ouds.
  const [loaded, setLoaded] = useState<{ url: string; page: PageDetail } | null>(null)
  const [failed, setFailed] = useState<{ url: string; error: SiteChangesError } | null>(null)
  const [refreshError, setRefreshError] = useState<string | null>(null)
  // Alleen het antwoord op het laatste verzoek telt (snel wisselen of meerdere acties achter elkaar).
  const detailRequest = useRef(0)

  const loadPages = useCallback(
    () =>
      fetchPages(customerId)
        .then((data) => {
          setPages(data)
          setPagesError(null)
        })
        .catch((err: Error) => setPagesError(err.message)),
    [customerId]
  )

  useEffect(() => {
    void loadPages()
  }, [loadPages])

  const allPages = useMemo(() => pages?.pages ?? [], [pages])

  // Een URL uit een link kan net anders gespeld zijn (slash aan het eind); dan de lijstversie nemen.
  const selectedPage = useMemo(() => {
    if (!selectedUrl) return null
    const key = urlKey(selectedUrl)
    return allPages.find((p) => urlKey(p.url) === key) ?? null
  }, [allPages, selectedUrl])

  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return allPages.filter(
      (p) =>
        // De gekozen pagina blijft in de lijst staan, ook als het laatste punt net is afgevinkt.
        (p === selectedPage || !onlyOpen || p.open_count + p.approved_count > 0) &&
        (!needle || p.path.toLowerCase().includes(needle) || (p.title ?? "").toLowerCase().includes(needle))
    )
  }, [allPages, onlyOpen, search, selectedPage])

  // Rechts staat altijd een pagina: de gekozen (ook als die niet in de lijst staat), anders de eerste.
  const activeUrl = selectedPage?.url ?? selectedUrl ?? visible[0]?.url ?? null
  const activeSummary = selectedPage ?? (selectedUrl ? null : visible[0] ?? null)

  const detail = loaded && activeUrl === loaded.url ? loaded.page : null
  const detailError = failed && activeUrl === failed.url ? failed.error : null

  const loadDetail = useCallback(
    (url: string, initial: boolean) => {
      const request = ++detailRequest.current
      return fetchPageDetail(customerId, url)
        .then((page) => {
          if (request !== detailRequest.current) return
          setLoaded({ url, page })
          setFailed(null)
          setRefreshError(null)
        })
        .catch((err: Error) => {
          if (request !== detailRequest.current) return
          const error = err instanceof SiteChangesError ? err : new SiteChangesError(err.message, 0)
          if (initial) setFailed({ url, error })
          else setRefreshError(error.message)
        })
    },
    [customerId]
  )

  useEffect(() => {
    if (!activeUrl || !pages?.has_sources) return
    void loadDetail(activeUrl, true)
  }, [activeUrl, pages?.has_sources, loadDetail])

  function selectPage(url: string) {
    setSelectedUrl(url)
    setRefreshError(null)
    writeUrlParams({ fase: "aanpassingen", url })
  }

  // Na een actie: direct lokaal bijwerken, daarna pagina en tellers opnieuw ophalen
  // (een item kan van lijst wisselen, bijv. goedgekeurd → gedaan).
  const handleItemChanged = useCallback(
    (next: ChangeItem) => {
      setLoaded((current) => (current ? { ...current, page: applyLocal(current.page, next) } : current))
      if (activeUrl) void loadDetail(activeUrl, false)
      void loadPages()
    },
    [activeUrl, loadDetail, loadPages]
  )

  const handleChecked = useCallback(
    (page: PageDetail) => {
      if (!activeUrl) return
      detailRequest.current++ // een lopende verversing mag dit antwoord niet overschrijven
      setLoaded({ url: activeUrl, page })
      setFailed(null)
      setRefreshError(null)
      void loadPages()
    },
    [activeUrl, loadPages]
  )

  const totals = pages?.totals

  return (
    <PhasePanel
      title="Aanpassingen"
      description={
        <>
          Per pagina wat er nog moet gebeuren en wat al gedaan is. Beoordeel de voorstellen, voer ze zelf door in
          WordPress en laat daarna controleren of de wijziging op de live pagina staat.
        </>
      }
    >
      {pages === null && !pagesError && <p className="text-sm text-muted-foreground">Pagina&apos;s laden…</p>}
      {pagesError && (
        <PanelRow tone="error" className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <span className="min-w-0 flex-1">De pagina&apos;s konden niet worden geladen. ({pagesError})</span>
          <Button size="sm" variant="outline" onClick={() => void loadPages()}>
            Opnieuw proberen
          </Button>
        </PanelRow>
      )}

      {pages && !pages.has_sources && (
        <PanelRow tone="muted">
          Er zijn nog geen voltooide scans voor deze klant. Voer eerst een nulmeting (fase 1) of een content-scan (fase
          3) uit; daarna verschijnen hier per pagina de voorstellen en actiepunten.
        </PanelRow>
      )}

      {pages && pages.has_sources && (
        <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
          {/* Links: pagina's */}
          <aside className="overflow-hidden rounded-lg border bg-card lg:sticky lg:top-4 lg:self-start">
            <div className="space-y-2 border-b px-3 py-2">
              {totals && (
                <p className="text-xs text-muted-foreground">
                  {totals.open} open · {totals.approved} goedgekeurd · {totals.done} gedaan
                </p>
              )}
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Zoek op pad of titel"
                className="h-8 text-xs"
              />
              <label className="flex items-center gap-2 text-xs text-muted-foreground">
                <input type="checkbox" checked={onlyOpen} onChange={(e) => setOnlyOpen(e.target.checked)} />
                Alleen met open punten
              </label>
            </div>
            {visible.length === 0 ? (
              <p className="px-3 py-6 text-center text-sm text-muted-foreground">
                {allPages.length === 0 ? "Geen pagina's met voorstellen of actiepunten." : "Geen pagina's voor dit filter."}
              </p>
            ) : (
              <ul className="max-h-[70vh] divide-y overflow-y-auto">
                {visible.map((page) => {
                  const active = activeUrl !== null && urlKey(page.url) === urlKey(activeUrl)
                  return (
                    <li key={page.url}>
                      <button
                        type="button"
                        onClick={() => selectPage(page.url)}
                        aria-current={active ? "page" : undefined}
                        className={cn(
                          "flex w-full items-start gap-2 border-l-2 px-3 py-2 text-left",
                          active ? "border-l-primary bg-primary/10" : "border-l-transparent hover:bg-muted/50"
                        )}
                      >
                        <span className="min-w-0 flex-1">
                          <span className={cn("block truncate text-sm", active && "font-medium")}>{page.path}</span>
                          <span className="block truncate text-xs text-muted-foreground">
                            {page.title || "Geen meta titel"}
                          </span>
                        </span>
                        <PageCounts page={page} />
                      </button>
                    </li>
                  )
                })}
              </ul>
            )}
          </aside>

          {/* Rechts: alle punten van de gekozen pagina */}
          <section className="min-w-0 overflow-hidden rounded-lg border bg-card">
            {activeUrl ? (
              <>
                {refreshError && (
                  <p className="border-b px-5 py-2 text-xs text-amber-800 dark:text-amber-300">
                    De pagina kon niet worden ververst; wat hier staat, kan verouderd zijn. ({refreshError})
                  </p>
                )}
                <DetailPanel
                  key={activeUrl}
                  customerId={customerId}
                  summary={activeSummary}
                  detail={detail}
                  error={detailError}
                  onItemChanged={handleItemChanged}
                  onChecked={handleChecked}
                />
              </>
            ) : (
              <p className="px-5 py-10 text-center text-sm text-muted-foreground">Kies links een pagina.</p>
            )}
          </section>
        </div>
      )}
    </PhasePanel>
  )
}
