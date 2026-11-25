"use client"

// Paneel rechts over het bord met de details van één kaart: velden om te wijzigen, de gebundelde
// bevindingen, een link naar de bron en verwijderen. De kop komt direct uit de bordkaart; de rest
// (notitie, punten, bronlink) haalt het paneel zelf op met `fetchCard`.

import { useEffect, useState } from "react"
import Link from "next/link"
import { ArrowRight } from "lucide-react"

import { ErrorNote } from "@/components/analytics/states"
import { fieldClassName } from "@/components/settings/SettingsSection"
import { selectClass } from "@/components/klanten/analyses/form-controls"
import { shortUrl } from "@/components/klanten/analyses/result-parts"
import { SeverityBadge } from "@/components/livegang/shared"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import { AssigneeAvatar, KindBadge } from "@/components/werkvoorraad/parts"
import type { IssueSeverity } from "@/lib/launch-checklist"
import {
  fetchCard,
  formatDayMonth,
  KINDS,
  SOURCE_LABELS,
  sourceHref,
  STATUS_LABELS,
  STATUS_ORDER,
  WorkQueueError,
  type WorkBoardUser,
  type WorkCard,
  type WorkCardDetail,
  type WorkCardItem,
  type WorkCardPatch,
  type WorkKind,
  type WorkSource,
  type WorkStatus,
} from "@/lib/work-queue"
import { cn } from "@/lib/utils"

type WorkItemSheetProps = {
  cardId: string | null
  card: WorkCard | null
  users: WorkBoardUser[]
  onClose: () => void
  onPatch: (id: string, patch: WorkCardPatch) => Promise<WorkCardDetail | null>
  onMove: (id: string, toStatus: WorkStatus) => Promise<boolean>
  onDelete: (id: string) => Promise<boolean>
}

/** Aantal bevindingen dat zonder "meer tonen" zichtbaar is. */
const ITEMS_PAGE = 50

const labelClass = "text-xs font-semibold text-muted-foreground"

export function WorkItemSheet({ cardId, card, users, onClose, onPatch, onMove, onDelete }: WorkItemSheetProps) {
  // Het laatst geopende id blijft staan tijdens de sluitanimatie, zodat de inhoud niet wegspringt.
  const [shownId, setShownId] = useState(cardId)
  if (cardId && cardId !== shownId) setShownId(cardId)

  return (
    <Sheet open={cardId !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
        {shownId ? (
          <SheetBody
            key={shownId}
            id={shownId}
            card={card && card.id === shownId ? card : null}
            users={users}
            onClose={onClose}
            onPatch={onPatch}
            onMove={onMove}
            onDelete={onDelete}
          />
        ) : (
          <SheetHeader>
            <SheetTitle className="sr-only">Taak</SheetTitle>
          </SheetHeader>
        )}
      </SheetContent>
    </Sheet>
  )
}

type LoadState = "loading" | "ready" | "not_found" | "error"

function SheetBody({
  id,
  card,
  users,
  onClose,
  onPatch,
  onMove,
  onDelete,
}: Omit<WorkItemSheetProps, "cardId"> & { id: string }) {
  const [detail, setDetail] = useState<WorkCardDetail | null>(null)
  const [loadState, setLoadState] = useState<LoadState>("loading")
  const [loadError, setLoadError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    fetchCard(id, controller.signal)
      .then((result) => {
        setDetail(result)
        setLoadState("ready")
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        if (error instanceof WorkQueueError && error.status === 404) {
          setLoadState("not_found")
          return
        }
        setLoadError(error instanceof Error ? error.message : "Er ging iets mis.")
        setLoadState("error")
      })
    return () => controller.abort()
  }, [id, reloadKey])

  // Kop: meteen uit de bordkaart, of uit het detail als de kaart niet op het bord staat.
  const view: WorkCard | null = detail ?? card

  if (loadState === "not_found") {
    return (
      <>
        <SheetHeader>
          <SheetTitle>{view?.title ?? "Taak"}</SheetTitle>
          <SheetDescription>Deze taak bestaat niet meer.</SheetDescription>
        </SheetHeader>
        <div className="px-4">
          <Button variant="outline" onClick={onClose}>
            Sluiten
          </Button>
        </div>
      </>
    )
  }

  return (
    <>
      <SheetHeader className="gap-2 pr-10">
        {view ? (
          <>
            <KindBadge kind={view.kind} />
            <SheetTitle className="text-lg leading-snug break-words">{view.title}</SheetTitle>
            <SheetDescription>
              {view.customer_name} · {SOURCE_LABELS[view.source]}
            </SheetDescription>
          </>
        ) : (
          <>
            <Skeleton className="h-5 w-20" />
            <SheetTitle className="sr-only">Taak laden</SheetTitle>
            <Skeleton className="h-6 w-3/4" />
            <Skeleton className="h-4 w-1/2" />
          </>
        )}
      </SheetHeader>

      <div className="flex flex-col gap-6 px-4 pb-4">
        {loadState === "error" && (
          <div className="space-y-2">
            <ErrorNote>{loadError ?? "Laden mislukt."}</ErrorNote>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setLoadState("loading")
                setReloadKey((key) => key + 1)
              }}
            >
              Opnieuw proberen
            </Button>
          </div>
        )}

        {view && (
          <CardFields
            id={id}
            view={view}
            loaded={detail !== null}
            users={users}
            onPatch={onPatch}
            onMove={onMove}
            onSaved={setDetail}
            onMoved={(status) => setDetail((current) => (current ? { ...current, status } : current))}
          />
        )}

        {detail?.resolved_by_source && (
          <p className="text-sm text-muted-foreground">Vanzelf afgerond: de bron heeft niets meer open staan.</p>
        )}

        {detail && <DoneLine detail={detail} />}

        {detail ? (
          <NoteField id={id} detail={detail} onPatch={onPatch} onSaved={setDetail} />
        ) : (
          loadState === "loading" && (
            <div className="space-y-2">
              <Skeleton className="h-4 w-20" />
              <Skeleton className="h-20 w-full" />
            </div>
          )
        )}

        {detail ? (
          <ItemsSection detail={detail} />
        ) : (
          loadState === "loading" && (
            <div className="space-y-2">
              <Skeleton className="h-4 w-32" />
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
            </div>
          )
        )}

        {detail && <SourceSection detail={detail} />}
      </div>

      {view && (
        <DeleteFooter
          id={id}
          source={view.source}
          itemCount={view.item_count}
          onDelete={onDelete}
          onClose={onClose}
        />
      )}
    </>
  )
}

// --- Velden -----------------------------------------------------------------------------------

function CardFields({
  id,
  view,
  loaded,
  users,
  onPatch,
  onMove,
  onSaved,
  onMoved,
}: {
  id: string
  view: WorkCard
  loaded: boolean
  users: WorkBoardUser[]
  onPatch: WorkItemSheetProps["onPatch"]
  onMove: WorkItemSheetProps["onMove"]
  onSaved: (detail: WorkCardDetail) => void
  onMoved: (status: WorkStatus) => void
}) {
  const manual = view.source === "manual"
  // Tijdelijke waarden tijdens het opslaan; daarna (of bij een fout) geldt weer de kaart.
  const [pendingStatus, setPendingStatus] = useState<WorkStatus | null>(null)
  const [pendingAssignee, setPendingAssignee] = useState<string | null | undefined>(undefined)
  const [pendingKind, setPendingKind] = useState<WorkKind | null>(null)
  const [error, setError] = useState<string | null>(null)

  const status = pendingStatus ?? view.status
  const assignee = pendingAssignee !== undefined ? pendingAssignee : view.assignee_id
  const kind = pendingKind ?? view.kind
  const assigneeKnown = !view.assignee_id || users.some((user) => user.id === view.assignee_id)

  async function changeStatus(next: WorkStatus) {
    if (next === view.status) return
    setError(null)
    setPendingStatus(next)
    const ok = await onMove(id, next)
    setPendingStatus(null)
    if (ok) onMoved(next)
    else setError("Verplaatsen mislukt")
  }

  async function changeAssignee(value: string) {
    const next = value || null
    if (next === view.assignee_id) return
    setError(null)
    setPendingAssignee(next)
    const result = await onPatch(id, { assignee_id: next })
    setPendingAssignee(undefined)
    if (result) onSaved(result)
    else setError("Opslaan mislukt")
  }

  async function changeKind(next: WorkKind) {
    if (next === view.kind) return
    setError(null)
    setPendingKind(next)
    const result = await onPatch(id, { kind: next })
    setPendingKind(null)
    if (result) onSaved(result)
    else setError("Opslaan mislukt")
  }

  return (
    <div className="space-y-4">
      {manual && <TitleField id={id} title={view.title} onPatch={onPatch} onSaved={onSaved} />}

      <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <dt className={labelClass}>Klant</dt>
          <dd className="text-sm">{view.customer_name}</dd>
        </div>
        <div className="space-y-1.5">
          <dt className={labelClass}>
            {manual ? <label htmlFor={`${id}-kind`}>Soort</label> : "Soort"}
          </dt>
          <dd>
            {manual ? (
              <select
                id={`${id}-kind`}
                className={selectClass}
                value={kind}
                disabled={pendingKind !== null}
                onChange={(event) => void changeKind(event.target.value as WorkKind)}
              >
                {KINDS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            ) : (
              <KindBadge kind={view.kind} />
            )}
          </dd>
        </div>
        <div className="space-y-1.5">
          <dt className={labelClass}>
            <label htmlFor={`${id}-status`}>Status</label>
          </dt>
          <dd>
            <select
              id={`${id}-status`}
              className={selectClass}
              value={status}
              disabled={pendingStatus !== null || !loaded}
              onChange={(event) => void changeStatus(event.target.value as WorkStatus)}
            >
              {STATUS_ORDER.map((option) => (
                <option key={option} value={option}>
                  {STATUS_LABELS[option]}
                </option>
              ))}
            </select>
          </dd>
        </div>
        <div className="space-y-1.5">
          <dt className={labelClass}>
            <label htmlFor={`${id}-assignee`}>Medewerker</label>
          </dt>
          <dd className="flex items-center gap-2">
            <AssigneeAvatar
              userId={assignee}
              name={users.find((user) => user.id === assignee)?.name ?? (assignee ? view.assignee_name : null)}
              className="shrink-0"
            />
            <select
              id={`${id}-assignee`}
              className={selectClass}
              value={assignee ?? ""}
              disabled={pendingAssignee !== undefined}
              onChange={(event) => void changeAssignee(event.target.value)}
            >
              <option value="">Niet toegewezen</option>
              {!assigneeKnown && view.assignee_id && (
                <option value={view.assignee_id}>{view.assignee_name ?? "Onbekende medewerker"}</option>
              )}
              {users.map((user) => (
                <option key={user.id} value={user.id}>
                  {user.name}
                </option>
              ))}
            </select>
          </dd>
        </div>
      </dl>

      {error && <InlineError>{error}</InlineError>}
    </div>
  )
}

/** Titel van een eigen taak; opslaan bij blur of Enter. */
function TitleField({
  id,
  title,
  onPatch,
  onSaved,
}: {
  id: string
  title: string
  onPatch: WorkItemSheetProps["onPatch"]
  onSaved: (detail: WorkCardDetail) => void
}) {
  // `null` = niet aangeraakt: dan volgt het veld de kaart.
  const [draft, setDraft] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [state, setState] = useState<"saved" | "error" | "empty" | null>(null)

  async function save() {
    if (draft === null || saving) return
    const next = draft.trim()
    if (next === title) {
      setDraft(null)
      return
    }
    if (!next) {
      setState("empty")
      return
    }
    setSaving(true)
    const result = await onPatch(id, { title: next })
    setSaving(false)
    if (result) {
      onSaved(result)
      setDraft(null)
      setState("saved")
    } else {
      setState("error")
    }
  }

  return (
    <div className="space-y-1.5">
      <label htmlFor={`${id}-title`} className={labelClass}>
        Titel
      </label>
      <Input
        id={`${id}-title`}
        value={draft ?? title}
        maxLength={300}
        disabled={saving}
        aria-invalid={state === "empty" || undefined}
        onChange={(event) => {
          setDraft(event.target.value)
          setState(null)
        }}
        onBlur={() => void save()}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault()
            void save()
          }
        }}
      />
      {state === "saved" && <p className="text-xs text-muted-foreground">Opgeslagen</p>}
      {state === "error" && <InlineError>Opslaan mislukt</InlineError>}
      {state === "empty" && <InlineError>Een titel is verplicht</InlineError>}
    </div>
  )
}

/** Notitie; opslaan bij blur. */
function NoteField({
  id,
  detail,
  onPatch,
  onSaved,
}: {
  id: string
  detail: WorkCardDetail
  onPatch: WorkItemSheetProps["onPatch"]
  onSaved: (detail: WorkCardDetail) => void
}) {
  const saved = detail.note ?? ""
  const [draft, setDraft] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [state, setState] = useState<"saved" | "error" | null>(null)

  async function save() {
    if (draft === null || saving) return
    if (draft.trim() === saved.trim()) {
      setDraft(null)
      return
    }
    setSaving(true)
    const result = await onPatch(id, { note: draft.trim() || null })
    setSaving(false)
    if (result) {
      onSaved(result)
      setDraft(null)
      setState("saved")
    } else {
      setState("error")
    }
  }

  return (
    <div className="space-y-1.5">
      <label htmlFor={`${id}-note`} className={labelClass}>
        Notitie
      </label>
      <textarea
        id={`${id}-note`}
        rows={4}
        className={cn(fieldClassName, "resize-y")}
        placeholder="Voeg een notitie toe"
        value={draft ?? saved}
        disabled={saving}
        onChange={(event) => {
          setDraft(event.target.value)
          setState(null)
        }}
        onBlur={() => void save()}
      />
      {state === "saved" && <p className="text-xs text-muted-foreground">Opgeslagen</p>}
      {state === "error" && <InlineError>Opslaan mislukt</InlineError>}
    </div>
  )
}

function DoneLine({ detail }: { detail: WorkCardDetail }) {
  const parts: string[] = []
  if (detail.source === "manual" && detail.created_by_name) {
    parts.push(`Aangemaakt door ${detail.created_by_name} op ${formatDayMonth(detail.created_at)}`)
  }
  if (detail.status === "done" && !detail.resolved_by_source) {
    const day = formatDayMonth(detail.done_at)
    const by = detail.done_by_name ? ` door ${detail.done_by_name}` : ""
    parts.push(`Afgerond${by}${day ? ` op ${day}` : ""}`)
  }
  if (parts.length === 0) return null
  return <p className="text-xs text-muted-foreground">{parts.join(" · ")}</p>
}

// --- Bevindingen en bron ----------------------------------------------------------------------

function isIssueSeverity(value: string | null): value is IssueSeverity {
  return value === "hoog" || value === "middel" || value === "laag"
}

function ItemsSection({ detail }: { detail: WorkCardDetail }) {
  const [visible, setVisible] = useState(ITEMS_PAGE)
  const items = detail.items
  if (items.length === 0) {
    if (detail.source === "manual") return null
    return (
      <section className="space-y-2">
        <h3 className="text-sm font-semibold">Bevindingen (0)</h3>
        <p className="text-sm text-muted-foreground">Er staan geen bevindingen meer open.</p>
      </section>
    )
  }
  const hidden = Math.max(0, items.length - visible)

  return (
    <section className="space-y-2">
      <h3 className="text-sm font-semibold">
        Bevindingen ({items.length.toLocaleString("nl-NL")})
      </h3>
      <ul className="divide-y rounded-lg border">
        {items.slice(0, visible).map((item) => (
          <ItemRow key={item.key} item={item} />
        ))}
      </ul>
      {hidden > 0 && (
        <div className="flex justify-center">
          <Button
            variant="ghost"
            size="sm"
            className="font-medium text-muted-foreground"
            onClick={() => setVisible((count) => count + ITEMS_PAGE)}
          >
            Meer tonen ({hidden.toLocaleString("nl-NL")})
          </Button>
        </div>
      )}
    </section>
  )
}

function ItemRow({ item }: { item: WorkCardItem }) {
  const location = item.path || (item.url ? shortUrl(item.url) : null)
  return (
    <li className="flex items-start gap-3 px-3 py-2.5">
      <div className="min-w-0 flex-1 space-y-0.5">
        <p className="text-sm break-words">{item.title}</p>
        {location &&
          (item.url ? (
            <a
              href={item.url}
              target="_blank"
              rel="noreferrer noopener"
              title={item.url}
              className="block truncate text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
            >
              {location}
            </a>
          ) : (
            <p className="truncate text-xs text-muted-foreground" title={location}>
              {location}
            </p>
          ))}
      </div>
      {isIssueSeverity(item.severity) && (
        <span className="shrink-0">
          <SeverityBadge severity={item.severity} />
        </span>
      )}
    </li>
  )
}

function SourceSection({ detail }: { detail: WorkCardDetail }) {
  const href = sourceHref(detail.source_link)
  const showLink = href !== null && href.startsWith("/dashboard/")
  const siteChanges = detail.source === "site_changes"
  if (!showLink && !siteChanges) return null
  return (
    <section className="space-y-2">
      {showLink && (
        <Button asChild variant="outline">
          <Link href={href}>
            Open in {SOURCE_LABELS[detail.source]}
            <ArrowRight aria-hidden="true" />
          </Link>
        </Button>
      )}
      {siteChanges && (
        <p className="text-sm text-muted-foreground">
          Afronden gebeurt in Aanpassingen: deze kaart gaat vanzelf naar Klaar als alles op de pagina is
          doorgevoerd of afgewezen.
        </p>
      )}
    </section>
  )
}

// --- Verwijderen ------------------------------------------------------------------------------

function deleteExplanation(source: WorkSource, itemCount: number): string {
  switch (source) {
    case "scan":
      return `De ${itemCount.toLocaleString("nl-NL")} bevindingen krijgen in de SEO/GEO-scan de status genegeerd. Deze kaart komt niet terug.`
    case "analysis":
      return "Dit zoekwoord komt niet meer terug op de werkvoorraad. De verbeterpunten blijven in de analyse staan."
    case "search_console":
      return "Deze pagina's komen niet meer terug op de werkvoorraad."
    case "site_changes":
      return "De voorstellen blijven open in Aanpassingen; ze verdwijnen alleen van de werkvoorraad."
    case "manual":
      return "De taak wordt verwijderd."
  }
}

function DeleteFooter({
  id,
  source,
  itemCount,
  onDelete,
  onClose,
}: {
  id: string
  source: WorkSource
  itemCount: number
  onDelete: WorkItemSheetProps["onDelete"]
  onClose: () => void
}) {
  const [confirming, setConfirming] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [failed, setFailed] = useState(false)

  async function remove() {
    setDeleting(true)
    setFailed(false)
    const ok = await onDelete(id)
    setDeleting(false)
    if (ok) onClose()
    else setFailed(true)
  }

  return (
    <div className="mt-auto border-t p-4">
      {confirming ? (
        <div className="space-y-3" role="group" aria-label="Verwijderen bevestigen">
          <p className="text-sm">{deleteExplanation(source, itemCount)}</p>
          <div className="flex flex-wrap gap-2">
            <Button variant="destructive" disabled={deleting} onClick={() => void remove()}>
              {deleting ? "Verwijderen…" : "Verwijderen"}
            </Button>
            <Button
              variant="outline"
              disabled={deleting}
              onClick={() => {
                setConfirming(false)
                setFailed(false)
              }}
            >
              Annuleren
            </Button>
          </div>
          {failed && <InlineError>Verwijderen mislukt</InlineError>}
        </div>
      ) : (
        <Button
          variant="ghost"
          className="text-red-700 hover:text-red-800 dark:text-red-400 dark:hover:text-red-300"
          onClick={() => setConfirming(true)}
        >
          Verwijderen
        </Button>
      )}
    </div>
  )
}

function InlineError({ children }: { children: React.ReactNode }) {
  return (
    <p role="alert" className="text-xs text-red-700 dark:text-red-400">
      {children}
    </p>
  )
}
