"use client"

import {
  AlertTriangle,
  ArrowRight,
  Check,
  CheckCircle2,
  Copy,
  ExternalLink,
  Loader2,
  RefreshCw,
  RotateCcw,
  Square,
  ThumbsDown,
  ThumbsUp,
  Upload,
} from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"

import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import {
  ReplacedDefaultTypes,
  SchemaEntities,
  SchemaOmitted,
  SchemaPlaceholders,
  SchemaProblems,
  SchemaScriptView,
  SchemaStaleNotice,
  SchemaTargetInfo,
} from "@/components/livegang/SchemaMarkupParts"
import { Pill, type Tone } from "@/components/livegang/shared"
import {
  createSchemaMarkup,
  fetchSchemaOverview,
  formatDateTime,
  PAGE_TYPE_LABELS,
  placeSchemaMarkup,
  reviewSchemaMarkup,
  type LaunchScanPage,
  type SchemaMarkupResponse,
  type SchemaReviewStatus,
} from "@/lib/launch-checklist"
import { cn } from "@/lib/utils"

/** Maximaal zoveel schema's tegelijk laten maken (elk is één modelaanroep van ~10 s). */
const GENERATE_CONCURRENCY = 3

type Step = "generate" | "review" | "place"
type RunStatus = "idle" | "wait" | "busy" | "done" | "error" | "stopped"
type ReviewAction = SchemaReviewStatus | "regenerate"

type Entry = {
  id: string
  url: string
  path: string
  title: string | null
  pageType: string | null
  /** Huidig voorstel; null = (nog) geen voorstel. */
  result: SchemaMarkupResponse | null
  gen: RunStatus
  genError: string | null
  /** Lopende beoordeling of nieuwe generatie vanuit stap 2. */
  action: ReviewAction | null
  actionError: string | null
  place: RunStatus
  placeError: string | null
}

const STEPS: { key: Step; label: string }[] = [
  { key: "generate", label: "Genereren" },
  { key: "review", label: "Controleren" },
  { key: "place", label: "Doorzetten" },
]

function newEntry(page: LaunchScanPage): Entry {
  return {
    id: page.id,
    url: page.url,
    path: page.path,
    title: page.title,
    pageType: page.page_type,
    result: null,
    gen: "idle",
    genError: null,
    action: null,
    actionError: null,
    place: "idle",
    placeError: null,
  }
}

/** Stap 1 maakt een voorstel als er geen is, of als de typekeuze na het voorstel is gewijzigd. */
function needsGeneration(result: SchemaMarkupResponse | null) {
  return !result || !!result.stale
}

function reviewOf(e: Entry): SchemaReviewStatus {
  return e.result?.review_status ?? "pending"
}

/** Er is een script om te beoordelen (niet "niets nodig"). */
function hasProposal(e: Entry) {
  return !!e.result && !e.result.nothing_missing && !!e.result.script
}

/** Het goedgekeurde voorstel staat al actueel op de site: telt als gedaan. */
function isPlacedCurrent(e: Entry) {
  return hasProposal(e) && reviewOf(e) === "approved" && !!e.result?.placement?.current
}

/** Goedgekeurd, plaatsbaar en nog niet (actueel) op de site. */
function needsPlacing(e: Entry) {
  return hasProposal(e) && reviewOf(e) === "approved" && !!e.result?.can_place && !e.result?.placement?.current
}

function isToReview(e: Entry) {
  return hasProposal(e) && reviewOf(e) === "pending" && !!e.result?.can_place
}

function reviewBadge(e: Entry): { label: string; tone: Tone } {
  if (!e.result) {
    if (e.gen === "error") return { label: "Fout", tone: "red" }
    if (e.gen === "wait" || e.gen === "busy") return { label: "Wordt gemaakt", tone: "blue" }
    return { label: "Geen voorstel", tone: "muted" }
  }
  if (e.result.nothing_missing) return { label: "Niets nodig", tone: "muted" }
  if (!e.result.script) return { label: "Geen voorstel", tone: "muted" }
  const status = reviewOf(e)
  if (status === "approved") {
    return e.result.placement?.current ? { label: "Al geplaatst", tone: "green" } : { label: "Goedgekeurd", tone: "green" }
  }
  if (status === "rejected") return { label: "Afgekeurd", tone: "red" }
  if (!e.result.can_place) return { label: "Kan niet geplaatst worden", tone: "amber" }
  return { label: "Te beoordelen", tone: "blue" }
}

function genBadge(e: Entry): { label: string; tone: Tone } {
  switch (e.gen) {
    case "wait":
      return { label: "Wacht", tone: "muted" }
    case "busy":
      return { label: "Bezig…", tone: "blue" }
    case "done":
      return e.result?.nothing_missing ? { label: "Niets nodig", tone: "muted" } : { label: "Klaar", tone: "green" }
    case "error":
      return { label: "Fout", tone: "red" }
    case "stopped":
      return { label: "Niet gestart", tone: "muted" }
    default:
      return e.result ? { label: "Had al een voorstel", tone: "muted" } : { label: "—", tone: "muted" }
  }
}

function placeBadge(e: Entry): { label: string; tone: Tone } {
  switch (e.place) {
    case "wait":
      return { label: "Wacht", tone: "muted" }
    case "busy":
      return { label: "Bezig…", tone: "blue" }
    case "done":
      return e.result?.placement?.verified
        ? { label: "Geplaatst en zichtbaar", tone: "green" }
        : { label: "Geplaatst, nog niet teruggevonden", tone: "amber" }
    case "error":
      return { label: "Mislukt", tone: "red" }
    case "stopped":
      return { label: "Niet gestart", tone: "muted" }
    default:
      return { label: "—", tone: "muted" }
  }
}

function hostOf(url: string) {
  try {
    return new URL(url).host
  } catch {
    return url
  }
}

function ProgressBar({ done, total }: { done: number; total: number }) {
  const pct = total ? Math.round((100 * done) / total) : 0
  return (
    <div className="space-y-1">
      <div className="h-2 overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${pct}%` }} />
      </div>
      <p className="text-xs tabular-nums text-muted-foreground">
        {done} van {total} klaar
      </p>
    </div>
  )
}

/**
 * Schema voor meerdere pagina's in drie stappen: ontbrekende voorstellen laten maken, elk voorstel door
 * een mens laten goed- of afkeuren, en alleen de goedgekeurde voorstellen één voor één via Rank Math op
 * de live site zetten (de backend controleert de goedkeuring nogmaals). Er is bewust geen "alles
 * goedkeuren". Mount per opening, zodat elke sessie met een schone staat begint.
 */
export function SchemaBulkDialog({
  scanId,
  pages,
  onClose,
  onResult,
}: {
  scanId: string
  /** De geselecteerde (indexeerbare) pagina's, max. 200. */
  pages: LaunchScanPage[]
  onClose: () => void
  /** Na elk antwoord met een voorstel, ook na sluiten: zodat de lijst zonder herladen bijgewerkt wordt. */
  onResult: (pageId: string, result: SchemaMarkupResponse) => void
}) {
  // Volgorde en inhoud vastleggen bij openen; de lijst erachter kan intussen veranderen.
  const [order] = useState(() => pages.map((p) => p.id))
  const [entries, setEntries] = useState<Record<string, Entry>>(() =>
    Object.fromEntries(pages.map((p) => [p.id, newEntry(p)]))
  )
  const [loaded, setLoaded] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [step, setStep] = useState<Step>("generate")
  const [skippedGenerate, setSkippedGenerate] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [genIds, setGenIds] = useState<string[]>([])
  /** Pagina's uit stap 1 waarvan een verouderd voorstel opnieuw is (of wordt) gemaakt. */
  const [regenIds, setRegenIds] = useState<string[]>([])
  const [placing, setPlacing] = useState(false)
  const [placeIds, setPlaceIds] = useState<string[]>([])
  const [stopping, setStopping] = useState(false)
  const [confirmPlace, setConfirmPlace] = useState(false)
  const [confirmClose, setConfirmClose] = useState(false)
  const [activeId, setActiveId] = useState<string | null>(null)
  const [copied, setCopied] = useState<string | null>(null)

  // Na sluiten (unmount) of "Stoppen" worden er geen nieuwe aanvragen gestart; lopende maken af.
  const aliveRef = useRef(true)
  const stopRef = useRef(false)
  // Eén overzichtsaanvraag bij openen, ook als React (StrictMode) het effect dubbel draait.
  const startedRef = useRef(false)
  const itemRefs = useRef(new Map<string, HTMLButtonElement>())

  function patch(id: string, changes: Partial<Entry> | ((e: Entry) => Partial<Entry>)) {
    setEntries((current) => {
      const e = current[id]
      if (!e) return current
      return { ...current, [id]: { ...e, ...(typeof changes === "function" ? changes(e) : changes) } }
    })
  }

  function patchMany(ids: string[], changes: (e: Entry) => Partial<Entry> | null) {
    setEntries((current) => {
      const next = { ...current }
      for (const id of ids) {
        const e = next[id]
        const c = e && changes(e)
        if (c) next[id] = { ...e, ...c }
      }
      return next
    })
  }

  // --- stap 1: overzicht en genereren ------------------------------------------------------------

  function loadOverview() {
    fetchSchemaOverview(scanId, order).then(
      (data) => {
        if (!aliveRef.current) return
        const byId = new Map(data.items.map((item) => [item.page_id, item]))
        setEntries((current) => {
          const next = { ...current }
          for (const id of order) {
            const item = byId.get(id)
            const e = next[id]
            if (!item || !e) continue
            next[id] = {
              ...e,
              url: item.url || e.url,
              path: item.path || e.path,
              title: item.title ?? e.title,
              pageType: item.page_type ?? e.pageType,
              result: item.result,
            }
          }
          return next
        })
        for (const item of data.items) if (item.result) onResult(item.page_id, item.result)
        setLoaded(true)
        // Zonder voorstel, of met een voorstel van vóór een gewijzigde typekeuze (dat wordt opnieuw gemaakt).
        const todo = order.filter((id) => needsGeneration(byId.get(id)?.result ?? null))
        if (todo.length === 0) {
          setSkippedGenerate(true)
          setStep("review")
        } else {
          void runGeneration(todo, new Set(todo.filter((id) => !!byId.get(id)?.result?.stale)))
        }
      },
      (err: unknown) => {
        if (!aliveRef.current) return
        setLoadError((err as Error).message)
      }
    )
  }

  useEffect(() => {
    aliveRef.current = true
    return () => {
      aliveRef.current = false
    }
  }, [])

  useEffect(() => {
    if (startedRef.current) return
    startedRef.current = true
    loadOverview()
    // Alleen bij openen; de dialog wordt per opening opnieuw gemount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function retryOverview() {
    setLoadError(null)
    loadOverview()
  }

  /**
   * Maakt voorstellen voor `ids`. Pagina's in `regenerateIds` hebben een verouderd voorstel (`stale`) en
   * worden echt opnieuw gemaakt; de rest krijgt een opgeslagen voorstel terug of een nieuw.
   */
  async function runGeneration(ids: string[], regenerateIds: Set<string>) {
    if (ids.length === 0) return
    stopRef.current = false
    setStopping(false)
    setGenerating(true)
    setStep("generate")
    setGenIds((current) => [...current, ...ids.filter((id) => !current.includes(id))])
    setRegenIds((current) => [...current, ...[...regenerateIds].filter((id) => !current.includes(id))])
    patchMany(ids, () => ({ gen: "wait", genError: null }))

    let cursor = 0
    let failed = 0
    const worker = async () => {
      while (cursor < ids.length && aliveRef.current && !stopRef.current) {
        const id = ids[cursor++]
        patch(id, { gen: "busy" })
        try {
          const result = await createSchemaMarkup(scanId, id, regenerateIds.has(id))
          onResult(id, result)
          patch(id, { result, gen: "done", genError: null })
        } catch (err) {
          failed++
          patch(id, { gen: "error", genError: (err as Error).message })
        }
      }
    }
    await Promise.all(Array.from({ length: Math.min(GENERATE_CONCURRENCY, ids.length) }, () => worker()))

    const interrupted = stopRef.current || !aliveRef.current
    patchMany(ids, (e) => (e.gen === "wait" ? { gen: "stopped" } : null))
    setGenerating(false)
    setStopping(false)
    if (!interrupted && failed === 0) setStep("review")
  }

  // --- stap 2: controleren ------------------------------------------------------------------------

  function review(id: string, status: SchemaReviewStatus) {
    // De getoonde pagina vastzetten: anders springt de standaardkeuze (eerste te beoordelen) door.
    setActiveId(id)
    patch(id, { action: status, actionError: null })
    reviewSchemaMarkup(scanId, id, status).then(
      (result) => {
        onResult(id, result)
        patch(id, { result, action: null })
      },
      (err: unknown) => patch(id, { action: null, actionError: (err as Error).message })
    )
  }

  /** Met voorstel: echt opnieuw genereren (beoordeling vervalt). Zonder: alsnog maken. */
  function regenerate(id: string) {
    const again = !!entries[id]?.result
    setActiveId(id)
    patch(id, { action: "regenerate", actionError: null })
    setCopied(null)
    createSchemaMarkup(scanId, id, again).then(
      (result) => {
        onResult(id, result)
        patch(id, (e) => ({
          result,
          action: null,
          gen: e.gen === "error" || e.gen === "stopped" ? "done" : e.gen,
          genError: null,
        }))
      },
      (err: unknown) => patch(id, { action: null, actionError: (err as Error).message })
    )
  }

  async function copyScript(id: string) {
    const script = entries[id]?.result?.script
    if (!script) return
    try {
      await navigator.clipboard.writeText(script)
      setCopied(id)
      setTimeout(() => setCopied((current) => (current === id ? null : current)), 2000)
    } catch {
      patch(id, { actionError: "Kopiëren naar het klembord is mislukt." })
    }
  }

  // --- stap 3: doorzetten -------------------------------------------------------------------------

  async function runPlacement(ids: string[]) {
    if (ids.length === 0) return
    stopRef.current = false
    setStopping(false)
    setConfirmPlace(false)
    setPlacing(true)
    setPlaceIds((current) => [...current, ...ids.filter((id) => !current.includes(id))])
    patchMany(ids, () => ({ place: "wait", placeError: null }))

    // Eén voor één: de klantsite niet belasten. Een fout stopt de rest niet.
    for (const id of ids) {
      if (!aliveRef.current || stopRef.current) break
      patch(id, { place: "busy" })
      try {
        const result = await placeSchemaMarkup(scanId, id, { requireApproved: true })
        onResult(id, result)
        patch(id, { result, place: "done", placeError: null })
      } catch (err) {
        patch(id, { place: "error", placeError: (err as Error).message })
      }
    }

    patchMany(ids, (e) => (e.place === "wait" ? { place: "stopped" } : null))
    setPlacing(false)
    setStopping(false)
  }

  // --- afgeleide gegevens -------------------------------------------------------------------------

  const list = useMemo(() => order.map((id) => entries[id]).filter((e): e is Entry => !!e), [order, entries])
  const toPlace = useMemo(() => list.filter(needsPlacing), [list])
  const firstToReview = list.find(isToReview)?.id ?? null
  const currentId = activeId && entries[activeId] ? activeId : (firstToReview ?? order[0] ?? null)
  const current = currentId ? entries[currentId] : null

  const proposals = list.filter(hasProposal)
  const reviewedCount = proposals.filter((e) => reviewOf(e) !== "pending").length
  const reviewTotal = proposals.filter((e) => reviewOf(e) !== "pending" || e.result?.can_place).length
  const approvedCount = proposals.filter((e) => reviewOf(e) === "approved").length

  const genList = genIds.map((id) => entries[id]).filter((e): e is Entry => !!e)
  const genDone = genList.filter((e) => e.gen === "done" || e.gen === "error").length
  const missingIds = list
    .filter((e) => needsGeneration(e.result) && e.gen !== "busy" && e.gen !== "wait")
    .map((e) => e.id)
  const missingStaleIds = missingIds.filter((id) => !!entries[id]?.result?.stale)
  const hadProposalCount = list.filter((e) => e.result && e.gen === "idle").length

  const placeList = placeIds.map((id) => entries[id]).filter((e): e is Entry => !!e)
  const placeFinished = placeList.filter((e) => e.place === "done" || e.place === "error").length
  const placedOk = placeList.filter((e) => e.place === "done")
  const placedVisible = placedOk.filter((e) => e.result?.placement?.verified).length
  const placeFailed = placeList.filter((e) => e.place === "error")
  const placeStopped = placeList.filter((e) => e.place === "stopped").length
  const alreadyCurrent = list.filter((e) => isPlacedCurrent(e) && !placeIds.includes(e.id)).length
  const notGoing = list.filter((e) => hasProposal(e) && !needsPlacing(e) && !isPlacedCurrent(e)).length
  const replacingDefaults = toPlace.filter((e) => (e.result?.replaces_default_types ?? []).length > 0).length

  const siteNames = [...new Set(list.map((e) => e.result?.placement?.site_name).filter((n): n is string => !!n))]
  const host = list[0] ? hostOf(list[0].url) : ""
  const siteLabel = siteNames.length ? `${siteNames.join(", ")} (${host})` : host

  const running = generating || placing

  function select(id: string) {
    setActiveId(id)
    setCopied(null)
    const el = itemRefs.current.get(id)
    el?.scrollIntoView({ block: "nearest" })
    el?.focus({ preventScroll: true })
  }

  function nextToReview() {
    if (!list.length) return
    const start = currentId ? order.indexOf(currentId) : -1
    for (let i = 1; i <= list.length; i++) {
      const e = entries[order[(start + i) % order.length]]
      if (e && e.id !== currentId && isToReview(e)) return select(e.id)
    }
  }

  // Pijltjes omhoog/omlaag wisselen van pagina in stap 2 (niet in invoervelden of tijdens een bevestiging).
  useEffect(() => {
    if (step !== "review" || confirmClose) return
    function onKey(ev: KeyboardEvent) {
      if (ev.key !== "ArrowDown" && ev.key !== "ArrowUp") return
      const target = ev.target as HTMLElement | null
      if (target?.closest("input, textarea, select, [contenteditable='true']")) return
      if (!order.length) return
      ev.preventDefault()
      const index = currentId ? order.indexOf(currentId) : -1
      const nextIndex = Math.min(order.length - 1, Math.max(0, index + (ev.key === "ArrowDown" ? 1 : -1)))
      const id = order[nextIndex]
      setActiveId(id)
      setCopied(null)
      const el = itemRefs.current.get(id)
      el?.scrollIntoView({ block: "nearest" })
      el?.focus({ preventScroll: true })
    }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [step, confirmClose, order, currentId])

  function stop() {
    stopRef.current = true
    setStopping(true)
  }

  function requestClose() {
    if (running) setConfirmClose(true)
    else onClose()
  }

  function forceClose() {
    stopRef.current = true
    onClose()
  }

  function stepState(key: Step): "current" | "done" | "todo" {
    if (key === step) return "current"
    const keys = STEPS.map((s) => s.key)
    return keys.indexOf(key) < keys.indexOf(step) ? "done" : "todo"
  }

  // --- weergave -----------------------------------------------------------------------------------

  return (
    <Dialog open onOpenChange={(open) => !open && requestClose()}>
      <DialogContent
        className="flex h-[94vh] w-[96vw] max-w-none flex-col gap-3 sm:max-w-[min(96vw,1400px)]"
        onInteractOutside={(e) => e.preventDefault()}
      >
        <DialogHeader className="pr-8">
          <DialogTitle>Schema voor {order.length} pagina&apos;s</DialogTitle>
          <DialogDescription>
            Laat ontbrekende voorstellen maken, keur elk voorstel zelf goed of af en zet daarna alleen de goedgekeurde
            voorstellen door naar Rank Math op {host || "de live site"}.
          </DialogDescription>
        </DialogHeader>

        <ol className="flex flex-wrap items-center gap-2 text-sm">
          {STEPS.map((s, i) => {
            const state = stepState(s.key)
            const skipped = s.key === "generate" && skippedGenerate && genIds.length === 0
            return (
              <li key={s.key} className="flex items-center gap-2">
                {i > 0 && <ArrowRight className="size-3.5 text-muted-foreground" />}
                <button
                  type="button"
                  disabled={!loaded || running || state === "current"}
                  onClick={() => {
                    setConfirmPlace(false)
                    setStep(s.key)
                  }}
                  aria-current={state === "current" ? "step" : undefined}
                  className={cn(
                    "flex items-center gap-1.5 rounded-full border px-3 py-1 disabled:cursor-default",
                    state === "current" && "border-primary bg-primary/10 font-medium text-foreground",
                    state === "done" && "text-foreground hover:bg-muted/50",
                    state === "todo" && "text-muted-foreground hover:bg-muted/50"
                  )}
                >
                  <span
                    className={cn(
                      "flex size-5 items-center justify-center rounded-full text-[11px] tabular-nums",
                      state === "current" ? "bg-primary text-primary-foreground" : "bg-muted"
                    )}
                  >
                    {state === "done" ? <Check className="size-3" /> : i + 1}
                  </span>
                  {s.label}
                  {skipped && <span className="text-xs text-muted-foreground">(overgeslagen)</span>}
                </button>
              </li>
            )
          })}
        </ol>

        {confirmClose && (
          <div className="space-y-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
            <p className="font-medium">Er lopen nog aanvragen. Toch sluiten?</p>
            <p className="text-xs">
              Lopende aanvragen maken op de achtergrond af en worden in de lijst bijgewerkt; er worden geen nieuwe
              gestart.
            </p>
            <div className="flex flex-wrap justify-end gap-2 pt-1">
              <Button size="sm" variant="outline" onClick={() => setConfirmClose(false)}>
                Doorgaan
              </Button>
              <Button size="sm" onClick={forceClose}>
                Toch sluiten
              </Button>
            </div>
          </div>
        )}

        <div className="min-h-0 flex-1">
          {step === "generate" && (
            <div className="flex h-full flex-col gap-3">
              {!loaded && !loadError && (
                <div className="flex items-center gap-2 rounded-md border bg-muted/30 px-3 py-6 text-sm text-muted-foreground">
                  <Loader2 className="size-4 animate-spin" /> Bestaande voorstellen ophalen…
                </div>
              )}
              {loadError && (
                <div className="flex flex-wrap items-center gap-3 rounded-md border border-red-300 px-3 py-2 text-sm text-red-700">
                  <span className="flex-1">{loadError}</span>
                  <Button size="sm" variant="outline" onClick={retryOverview}>
                    <RefreshCw /> Opnieuw proberen
                  </Button>
                </div>
              )}
              {loaded && (
                <>
                  <p className="text-sm text-muted-foreground">
                    {genIds.length > 0
                      ? `Voorstellen maken voor ${genIds.length} pagina's zonder actueel voorstel, maximaal ${GENERATE_CONCURRENCY} tegelijk.`
                      : "Alle pagina's hebben al een voorstel."}
                    {regenIds.length > 0 &&
                      ` Bij ${regenIds.length} daarvan zijn de schema-types gewijzigd na het vorige voorstel; die worden opnieuw gemaakt.`}
                    {hadProposalCount > 0 && ` ${hadProposalCount} pagina's hadden al een voorstel en worden niet opnieuw gemaakt.`}
                  </p>
                  {genIds.length > 0 && <ProgressBar done={genDone} total={genIds.length} />}
                  <ul className="min-h-0 flex-1 divide-y overflow-y-auto rounded-lg border">
                    {genList.map((e) => {
                      const badge = genBadge(e)
                      return (
                        <li key={e.id} className="flex items-start gap-3 px-3 py-2 text-sm">
                          <div className="min-w-0 flex-1">
                            <p className="truncate">{e.path || e.url}</p>
                            {e.gen === "error" && e.genError && <p className="text-xs text-red-700">{e.genError}</p>}
                          </div>
                          <Pill tone={badge.tone}>
                            {e.gen === "busy" && <Loader2 className="size-3 animate-spin" />}
                            {badge.label}
                          </Pill>
                        </li>
                      )
                    })}
                  </ul>
                  <div className="flex flex-wrap items-center justify-end gap-2">
                    {generating ? (
                      <Button size="sm" variant="outline" disabled={stopping} onClick={stop}>
                        {stopping ? <Loader2 className="animate-spin" /> : <Square />}
                        {stopping ? "Stoppen… lopende aanvragen maken af" : "Stoppen"}
                      </Button>
                    ) : (
                      <>
                        {missingIds.length > 0 && (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => void runGeneration(missingIds, new Set(missingStaleIds))}
                          >
                            <RefreshCw />{" "}
                            {missingStaleIds.length > 0 ? "Ontbrekende en verouderde voorstellen maken" : "Ontbrekende voorstellen maken"}{" "}
                            ({missingIds.length})
                          </Button>
                        )}
                        <Button size="sm" onClick={() => setStep("review")}>
                          Naar controleren <ArrowRight />
                        </Button>
                      </>
                    )}
                  </div>
                </>
              )}
            </div>
          )}

          {step === "review" && (
            <div className="grid h-full min-h-0 gap-3 lg:grid-cols-[320px_1fr]">
              <aside className="flex min-h-0 flex-col overflow-hidden rounded-lg border bg-card">
                <p className="border-b px-3 py-2 text-xs text-muted-foreground">
                  {reviewedCount} van {reviewTotal} beoordeeld, {approvedCount} goedgekeurd · ↑/↓ wisselt van pagina
                </p>
                <ul className="min-h-0 flex-1 divide-y overflow-y-auto">
                  {list.map((e) => {
                    const active = e.id === currentId
                    const badge = reviewBadge(e)
                    return (
                      <li key={e.id}>
                        <button
                          type="button"
                          ref={(el) => {
                            if (el) itemRefs.current.set(e.id, el)
                            else itemRefs.current.delete(e.id)
                          }}
                          onClick={() => select(e.id)}
                          className={cn(
                            "flex w-full items-start gap-2 border-l-2 px-3 py-2 text-left outline-none focus-visible:bg-muted/50",
                            active ? "border-l-primary bg-primary/10" : "border-l-transparent hover:bg-muted/50"
                          )}
                        >
                          <span className="min-w-0 flex-1">
                            <span className={cn("block truncate text-sm", active && "font-medium")}>{e.path || e.url}</span>
                            {e.title && <span className="block truncate text-xs text-muted-foreground">{e.title}</span>}
                          </span>
                          <Pill tone={badge.tone} className="mt-0.5 shrink-0">
                            {e.action && <Loader2 className="size-3 animate-spin" />}
                            {badge.label}
                          </Pill>
                        </button>
                      </li>
                    )
                  })}
                </ul>
                <div className="border-t p-2">
                  <Button size="sm" className="w-full" onClick={() => setStep("place")}>
                    Naar doorzetten ({toPlace.length}) <ArrowRight />
                  </Button>
                </div>
              </aside>

              <section className="min-h-0 overflow-y-auto rounded-lg border bg-card">
                {current ? (
                  <ReviewPane
                    entry={current}
                    copied={copied === current.id}
                    hasNextToReview={list.some((e) => e.id !== current.id && isToReview(e))}
                    onReview={(status) => review(current.id, status)}
                    onRegenerate={() => regenerate(current.id)}
                    onCopy={() => void copyScript(current.id)}
                    onNext={nextToReview}
                  />
                ) : (
                  <p className="p-4 text-sm text-muted-foreground">Geen pagina&apos;s.</p>
                )}
              </section>
            </div>
          )}

          {step === "place" && (
            <div className="flex h-full flex-col gap-3">
              <div className="space-y-1 text-sm">
                <p>
                  <strong>{toPlace.length}</strong> goedgekeurde schema&apos;s klaar om door te zetten naar{" "}
                  {siteLabel || "de live site"}.
                </p>
                {alreadyCurrent > 0 && (
                  <p className="text-xs text-muted-foreground">
                    {alreadyCurrent} pagina&apos;s staan al met het goedgekeurde voorstel op de site en gaan niet opnieuw mee.
                  </p>
                )}
                {notGoing > 0 && (
                  <p className="text-xs text-muted-foreground">
                    {notGoing} voorstellen zijn niet goedgekeurd of kunnen niet geplaatst worden en gaan niet mee.
                  </p>
                )}
              </div>

              {placeIds.length > 0 && <ProgressBar done={placeFinished} total={placeIds.length} />}

              {!placing && placeIds.length > 0 && (
                <div
                  className={cn(
                    "rounded-md border px-3 py-2 text-sm",
                    placeFailed.length
                      ? "border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200"
                      : "border-green-300 bg-green-50 text-green-900 dark:border-green-800 dark:bg-green-950/40 dark:text-green-200"
                  )}
                >
                  <p className="font-medium">
                    {placedOk.length} geplaatst ({placedVisible} zichtbaar op de pagina
                    {placedOk.length - placedVisible > 0 ? `, ${placedOk.length - placedVisible} nog niet teruggevonden` : ""})
                    {placeFailed.length > 0 ? `, ${placeFailed.length} mislukt` : ""}
                    {placeStopped > 0 ? `, ${placeStopped} niet gestart` : ""}.
                  </p>
                  {placedOk.length - placedVisible > 0 && (
                    <p className="text-xs">Niet teruggevonden komt vaak door caching; controleer die pagina&apos;s later.</p>
                  )}
                </div>
              )}

              <ul className="min-h-0 flex-1 divide-y overflow-y-auto rounded-lg border">
                {(placeIds.length > 0
                  ? [...placeList, ...toPlace.filter((e) => !placeIds.includes(e.id))]
                  : toPlace
                ).map((e) => {
                  const badge = e.place === "idle" ? { label: "Klaar om door te zetten", tone: "blue" as Tone } : placeBadge(e)
                  const replaces = e.result?.replaces_default_types ?? []
                  return (
                    <li key={e.id} className="flex items-start gap-3 px-3 py-2 text-sm">
                      <div className="min-w-0 flex-1 space-y-0.5">
                        <a href={e.url} target="_blank" rel="noreferrer noopener" className="block truncate hover:underline">
                          {e.path || e.url}
                        </a>
                        {e.place === "idle" && replaces.length > 0 && (
                          <p className="text-xs text-amber-800 dark:text-amber-300">
                            Standaardschema van Rank Math vervalt: {replaces.join(", ")}
                          </p>
                        )}
                        {e.place === "error" && e.placeError && <p className="text-xs text-red-700">{e.placeError}</p>}
                      </div>
                      <Pill tone={badge.tone} className="shrink-0">
                        {e.place === "busy" && <Loader2 className="size-3 animate-spin" />}
                        {badge.label}
                      </Pill>
                      {e.place === "error" && !placing && (
                        <Button size="sm" variant="outline" className="h-7" onClick={() => void runPlacement([e.id])}>
                          <RotateCcw /> Opnieuw proberen
                        </Button>
                      )}
                    </li>
                  )
                })}
                {placeIds.length === 0 && toPlace.length === 0 && (
                  <li className="px-3 py-6 text-center text-sm text-muted-foreground">
                    Nog niets goedgekeurd om door te zetten. Keur in de stap Controleren de voorstellen goed die naar de
                    site mogen.
                  </li>
                )}
              </ul>

              {confirmPlace && !placing && (
                <div className="space-y-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
                  <p className="font-medium">
                    {toPlace.length} schema&apos;s op de live site {siteLabel} zetten?
                  </p>
                  <p className="text-xs">
                    Het gaat om de live site: de goedgekeurde schema&apos;s komen via Rank Math direct op {toPlace.length}{" "}
                    pagina&apos;s en zijn meteen zichtbaar voor bezoekers en zoekmachines. Ze worden één voor één geplaatst.
                  </p>
                  {replacingDefaults > 0 && (
                    <p className="flex items-center gap-1.5 text-xs">
                      <AlertTriangle className="size-3.5 shrink-0" /> Bij {replacingDefaults} pagina&apos;s vervalt het
                      standaardschema van Rank Math.
                    </p>
                  )}
                  <div className="flex flex-wrap justify-end gap-2 pt-1">
                    <Button size="sm" variant="outline" onClick={() => setConfirmPlace(false)}>
                      Annuleren
                    </Button>
                    <Button size="sm" onClick={() => void runPlacement(toPlace.map((e) => e.id))}>
                      <Upload /> Ja, zet {toPlace.length} door
                    </Button>
                  </div>
                </div>
              )}

              <div className="flex flex-wrap items-center justify-end gap-2">
                {placing ? (
                  <Button size="sm" variant="outline" disabled={stopping} onClick={stop}>
                    {stopping ? <Loader2 className="animate-spin" /> : <Square />}
                    {stopping ? "Stoppen… lopende plaatsing maakt af" : "Stoppen"}
                  </Button>
                ) : (
                  <>
                    <Button size="sm" variant="outline" onClick={() => setStep("review")}>
                      Terug naar controleren
                    </Button>
                    <Button size="sm" disabled={toPlace.length === 0 || confirmPlace} onClick={() => setConfirmPlace(true)}>
                      <Upload /> Zet {toPlace.length} goedgekeurde schema&apos;s door
                    </Button>
                  </>
                )}
              </div>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}

/** Rechterdeel van stap 2: het voorstel van één pagina met de beoordelingsknoppen. */
function ReviewPane({
  entry,
  copied,
  hasNextToReview,
  onReview,
  onRegenerate,
  onCopy,
  onNext,
}: {
  entry: Entry
  copied: boolean
  hasNextToReview: boolean
  onReview: (status: SchemaReviewStatus) => void
  onRegenerate: () => void
  onCopy: () => void
  onNext: () => void
}) {
  const result = entry.result
  const status = reviewOf(entry)
  const busy = entry.action !== null
  const proposal = hasProposal(entry)
  const placement = result?.placement ?? null
  const placementOk = !!placement && placement.verified && placement.current
  const replaces = result?.replaces_default_types ?? []
  // Elk type op het hoogste niveau wordt een eigen schema in Rank Math.
  const schemaTypes = result?.types ?? []
  const blockedReason = proposal && !result?.can_place ? (result?.place_blocked_reason ?? "").trim() : ""
  const generating = entry.gen === "wait" || entry.gen === "busy"

  return (
    <div className="flex min-h-full flex-col">
      <div className="space-y-1 border-b px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <p className="min-w-0 flex-1 truncate font-medium">{entry.path || entry.url}</p>
          {entry.pageType && <Pill>{PAGE_TYPE_LABELS[entry.pageType] ?? entry.pageType}</Pill>}
        </div>
        {entry.title && <p className="truncate text-xs text-muted-foreground">{entry.title}</p>}
        <a
          href={entry.url}
          target="_blank"
          rel="noreferrer noopener"
          className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
        >
          <ExternalLink className="size-3" /> Open de live pagina
        </a>
      </div>

      <div className="flex-1 space-y-3 px-4 py-3">
        {entry.action === "regenerate" && (
          <div className="flex items-center gap-2 rounded-md border bg-muted/30 px-3 py-4 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" /> Nieuw schema maken… dit kan even duren.
          </div>
        )}

        {!result && entry.action !== "regenerate" && (
          <div className="space-y-2 text-sm">
            {generating ? (
              <p className="flex items-center gap-2 text-muted-foreground">
                <Loader2 className="size-4 animate-spin" /> Voorstel wordt gemaakt…
              </p>
            ) : entry.gen === "error" ? (
              <p className="text-red-700">Maken mislukt: {entry.genError}</p>
            ) : (
              <p className="text-muted-foreground">Voor deze pagina is nog geen voorstel gemaakt.</p>
            )}
          </div>
        )}

        {result?.nothing_missing && entry.action !== "regenerate" && (
          <div className="flex items-start gap-2 rounded-md border border-green-300 bg-green-50 px-3 py-3 text-sm text-green-900 dark:border-green-800 dark:bg-green-950/40 dark:text-green-200">
            <CheckCircle2 className="mt-0.5 size-4 shrink-0" />
            <p>
              {result.notes || "Het verwachte schema voor dit paginatype staat al op de pagina."} Er is niets gemaakt en
              er hoeft niets geplaatst te worden.
            </p>
          </div>
        )}

        {proposal && result && entry.action !== "regenerate" && (
          <>
            {status !== "pending" && (
              <p
                className={cn(
                  "flex items-center gap-1.5 rounded-md border px-3 py-2 text-sm font-medium",
                  status === "approved"
                    ? "border-green-300 bg-green-50 text-green-900 dark:border-green-800 dark:bg-green-950/40 dark:text-green-200"
                    : "border-red-300 bg-red-50 text-red-900 dark:border-red-800 dark:bg-red-950/40 dark:text-red-200"
                )}
              >
                {status === "approved" ? <ThumbsUp className="size-4" /> : <ThumbsDown className="size-4" />}
                {status === "approved" ? "Goedgekeurd" : "Afgekeurd"}
                {result.reviewed_at ? ` op ${formatDateTime(result.reviewed_at)}` : ""}
              </p>
            )}

            {placement && (
              <div
                className={cn(
                  "space-y-1 rounded-md border px-3 py-2 text-sm",
                  placementOk
                    ? "border-green-300 bg-green-50 text-green-900 dark:border-green-800 dark:bg-green-950/40 dark:text-green-200"
                    : "border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200"
                )}
              >
                <p className="flex items-center gap-1.5 font-medium">
                  {placementOk ? <CheckCircle2 className="size-4 shrink-0" /> : <AlertTriangle className="size-4 shrink-0" />}
                  Geplaatst in Rank Math op {formatDateTime(placement.placed_at)}
                  {placement.site_name ? ` (${placement.site_name})` : ""}
                </p>
                {placement.verified ? (
                  <p className="text-xs">Zichtbaar op de pagina.</p>
                ) : (
                  <p className="text-xs">Nog niet teruggevonden op de pagina, mogelijk door caching.</p>
                )}
                {!placement.current && (
                  <p className="text-xs">
                    Op de site staat een eerdere versie; dit voorstel is daarna gemaakt. Na goedkeuren kun je het
                    doorzetten.
                  </p>
                )}
              </div>
            )}

            {schemaTypes.length > 0 && (
              <p className="text-xs text-muted-foreground">
                {schemaTypes.length === 1
                  ? `Komt als één schema in Rank Math: ${schemaTypes[0]}`
                  : `Komt als ${schemaTypes.length} aparte schema's in Rank Math: ${schemaTypes.join(", ")}`}
              </p>
            )}

            {replaces.length > 0 && (
              <div className="space-y-1 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
                <p className="flex items-center gap-1.5 font-medium">
                  <AlertTriangle className="size-4 shrink-0" /> Het standaardschema van Rank Math voor deze pagina vervalt
                </p>
                <ReplacedDefaultTypes types={replaces} />
              </div>
            )}

            <SchemaStaleNotice stale={result.stale} />

            <SchemaTargetInfo result={result} />
            <SchemaEntities result={result} />

            <SchemaPlaceholders placeholders={result.placeholders} />
            <SchemaProblems problems={result.problems} />

            <SchemaScriptView key={entry.id} result={result} />

            <SchemaOmitted omitted={result.omitted} />

            {result.notes && <p className="text-xs text-muted-foreground">{result.notes}</p>}

            {!result.can_place && (
              <div className="space-y-2 rounded-md border bg-muted/30 px-3 py-2 text-sm">
                <p className="font-medium">Kan niet via Rank Math geplaatst worden</p>
                {blockedReason && <p className="text-xs text-muted-foreground">{blockedReason}</p>}
                <Button size="sm" variant="outline" onClick={onCopy}>
                  {copied ? <Check /> : <Copy />} {copied ? "Gekopieerd" : "Kopieer script"}
                </Button>
              </div>
            )}

            <p className="text-xs text-muted-foreground">Gemaakt op {formatDateTime(result.generated_at)}</p>
          </>
        )}

        {entry.actionError && <p className="text-sm text-red-600">{entry.actionError}</p>}
      </div>

      <div className="sticky bottom-0 flex flex-wrap items-center gap-2 border-t bg-card px-4 py-3">
        {proposal && result?.can_place && (
          <Button
            size="sm"
            disabled={busy || status === "approved"}
            onClick={() => onReview("approved")}
            className="bg-green-700 text-white hover:bg-green-800 dark:bg-green-600 dark:text-white dark:hover:bg-green-700"
          >
            {entry.action === "approved" ? <Loader2 className="animate-spin" /> : <ThumbsUp />} Goedkeuren
          </Button>
        )}
        {proposal && (
          <Button size="sm" variant="outline" disabled={busy || status === "rejected"} onClick={() => onReview("rejected")}>
            {entry.action === "rejected" ? <Loader2 className="animate-spin" /> : <ThumbsDown />} Afkeuren
          </Button>
        )}
        {proposal && status !== "pending" && (
          <Button size="sm" variant="ghost" disabled={busy} onClick={() => onReview("pending")}>
            {entry.action === "pending" ? <Loader2 className="animate-spin" /> : <RotateCcw />} Beoordeling wissen
          </Button>
        )}
        {!generating && (
          <Button
            size="sm"
            variant="ghost"
            disabled={busy}
            onClick={onRegenerate}
            title={result ? "Maakt een nieuw voorstel; de beoordeling vervalt." : undefined}
          >
            <RefreshCw /> {result ? "Opnieuw genereren" : entry.gen === "error" ? "Opnieuw proberen" : "Voorstel maken"}
          </Button>
        )}
        <Button size="sm" variant="outline" className="ml-auto" disabled={!hasNextToReview} onClick={onNext}>
          Volgende te beoordelen <ArrowRight />
        </Button>
      </div>
    </div>
  )
}
