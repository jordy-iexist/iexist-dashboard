"use client"

import { AlertTriangle, Check, CheckCheck, Copy, ExternalLink, Loader2, Pencil, RotateCcw, X } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Pill, SeverityBadge } from "@/components/livegang/shared"
import { formatDateTime } from "@/lib/launch-checklist"
import { TOPIC_LABELS, updateChange, type ChangeAction, type ChangeItem, type Topic } from "@/lib/site-changes"
import { cn } from "@/lib/utils"

/** Onderwerpen waarbij de lengte ertoe doet; daar tonen we het aantal tekens. */
const LENGTH_TOPICS = new Set<Topic>(["meta_title", "meta_description"])

const label = "text-xs font-medium uppercase tracking-wide text-muted-foreground sm:pt-0.5"

function sizeInfo(topic: Topic, value: string | null) {
  return value && LENGTH_TOPICS.has(topic) ? `${value.length} tekens` : null
}

/** Eén actie (approve/reject/…) op een item uitvoeren, met laadtoestand en inline fout. */
function useChangeAction(customerId: string, item: ChangeItem, onChanged: (next: ChangeItem) => void) {
  const [busy, setBusy] = useState<ChangeAction | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function run(action: ChangeAction, extra: { value?: string; note?: string } = {}) {
    setBusy(action)
    setError(null)
    try {
      onChanged(await updateChange(customerId, item, action, extra))
      return true
    } catch (err) {
      setError((err as Error).message)
      return false
    } finally {
      setBusy(null)
    }
  }

  return { busy, error, setError, run }
}

function CopyButton({ value, onError }: { value: string; onError: (message: string) => void }) {
  const [copied, setCopied] = useState(false)

  async function copy() {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      onError("Kopiëren is niet gelukt.")
    }
  }

  return (
    <Button size="icon" variant="ghost" className="size-8" title="Kopieer" aria-label="Kopieer" onClick={() => void copy()}>
      {copied ? <Check className="text-green-600" /> : <Copy />}
    </Button>
  )
}

function RefLink({ href }: { href: string | null }) {
  if (!href || !/^https?:\/\//.test(href)) return null
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer noopener"
      className="inline-flex max-w-full items-center gap-1 text-xs text-primary hover:underline"
    >
      <span className="truncate">{href}</span>
      <ExternalLink className="size-3 shrink-0" />
    </a>
  )
}

/** Inline bewerken van de voorgestelde tekst; opslaan = goedkeuren met deze waarde. */
function ValueEditor({
  topic,
  initial,
  onSave,
  onDone,
}: {
  topic: Topic
  initial: string
  onSave: (value: string) => Promise<boolean>
  onDone: () => void
}) {
  const [draft, setDraft] = useState(initial)
  const [saving, setSaving] = useState(false)
  const [confirmCancel, setConfirmCancel] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const dirty = draft !== initial
  const size = sizeInfo(topic, draft)

  useEffect(() => {
    textareaRef.current?.focus({ preventScroll: true })
  }, [])

  async function save() {
    if (!draft.trim() || saving) return
    setSaving(true)
    const ok = await onSave(draft.trim())
    // Bij succes verdwijnt de editor (het item is bijgewerkt); bij een fout blijft de tekst staan.
    if (ok) onDone()
    else setSaving(false)
  }

  function cancel() {
    if (dirty) setConfirmCancel(true)
    else onDone()
  }

  return (
    <div className="space-y-2">
      <textarea
        ref={textareaRef}
        value={draft}
        onChange={(ev) => {
          setDraft(ev.target.value)
          setConfirmCancel(false)
        }}
        onKeyDown={(ev) => {
          if (ev.key === "Escape") cancel()
          if (ev.key === "Enter" && (ev.metaKey || ev.ctrlKey)) void save()
        }}
        readOnly={saving}
        rows={Math.min(12, Math.max(3, draft.split("\n").length + 1))}
        aria-label="Voorstel bewerken"
        className={cn(
          "block w-full resize-y rounded-md border bg-background p-3 text-sm leading-relaxed outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
          saving && "opacity-70"
        )}
      />
      <p className="text-xs text-muted-foreground">
        {size ? `${size} · ` : ""}Opslaan keurt het voorstel goed met deze tekst.
      </p>
      {confirmCancel ? (
        <div className="space-y-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
          <p className="font-medium">Wijzigingen weggooien?</p>
          <p className="text-xs">De aangepaste tekst is nog niet opgeslagen en gaat verloren.</p>
          <div className="flex flex-wrap justify-end gap-2 pt-1">
            <Button size="sm" variant="outline" onClick={() => setConfirmCancel(false)}>
              Verder bewerken
            </Button>
            <Button size="sm" variant="destructive" onClick={onDone}>
              Wijzigingen weggooien
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap justify-end gap-2">
          <Button size="sm" variant="ghost" disabled={saving} onClick={cancel}>
            Annuleren
          </Button>
          <Button size="sm" disabled={saving || !draft.trim()} onClick={() => void save()}>
            {saving && <Loader2 className="animate-spin" />} Opslaan
          </Button>
        </div>
      )}
    </div>
  )
}

/** Bevestiging in de rij voor "Gedaan zonder controle", met optionele notitie. */
function ConfirmDone({
  busy,
  onConfirm,
  onCancel,
}: {
  busy: boolean
  onConfirm: (note: string) => void
  onCancel: () => void
}) {
  const [note, setNote] = useState("")
  return (
    <form
      className="space-y-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200"
      onSubmit={(e) => {
        e.preventDefault()
        onConfirm(note.trim())
      }}
    >
      <p className="font-medium">Markeren als gedaan zonder controle?</p>
      <p className="text-xs">Het dashboard controleert dan niet of dit op de live pagina staat.</p>
      <Input
        autoFocus
        value={note}
        onChange={(e) => setNote(e.target.value)}
        maxLength={500}
        placeholder="Notitie (optioneel)"
        className="h-8 bg-background text-sm text-foreground"
      />
      <div className="flex flex-wrap justify-end gap-2 pt-1">
        <Button size="sm" type="button" variant="outline" disabled={busy} onClick={onCancel}>
          Annuleren
        </Button>
        <Button size="sm" type="submit" disabled={busy}>
          {busy && <Loader2 className="animate-spin" />} Markeer als gedaan
        </Button>
      </div>
    </form>
  )
}

/** Gecontroleerd maar niet teruggezien op de live pagina. */
function NotLiveNotice({ item }: { item: ChangeItem }) {
  const detail = item.verify_detail
  if (!detail || item.verified !== false) return null
  return (
    <div className="space-y-1 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:bg-amber-900/20 dark:text-amber-200">
      <p className="flex items-start gap-1.5 font-medium">
        <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
        <span>{detail.message || "Nog niet live teruggezien."}</span>
      </p>
      {detail.live_value && (
        <p className="whitespace-pre-wrap [overflow-wrap:anywhere] text-xs">
          <span className="font-medium">Op de pagina staat nu:</span> {detail.live_value}
        </p>
      )}
      {detail.missing.length > 0 && (
        <div className="text-xs">
          <p className="font-medium">Ontbreekt nog:</p>
          <ul className="ml-4 list-disc">
            {detail.missing.map((line) => (
              <li key={line} className="[overflow-wrap:anywhere]">
                {line}
              </li>
            ))}
          </ul>
        </div>
      )}
      <p className="text-[11px] opacity-80">Gecontroleerd {formatDateTime(detail.checked_at)}</p>
    </div>
  )
}

/**
 * Eén open of goedgekeurd punt: een voorstel (Huidig / Voorstel / Waarom) of een
 * actiepunt uit een scan (titel, omschrijving, aanpak). Gebruik binnen een `<ul>`.
 */
export function ChangeRow({
  customerId,
  item,
  onChanged,
}: {
  customerId: string
  item: ChangeItem
  onChanged: (next: ChangeItem) => void
}) {
  const { busy, error, setError, run } = useChangeAction(customerId, item, onChanged)
  const [editing, setEditing] = useState(false)
  const [confirmDone, setConfirmDone] = useState(false)
  const isIssue = item.source_kind === "scan_issue" || item.proposed_value === null
  const approved = item.status === "goedgekeurd"
  const shownValue = approved ? item.approved_value ?? item.proposed_value : item.proposed_value
  const disabled = busy !== null

  const spin = (action: ChangeAction, icon: React.ReactNode) =>
    busy === action ? <Loader2 className="animate-spin" /> : icon

  const doneButton = (
    <Button
      size="sm"
      variant="ghost"
      className="h-7 px-2"
      disabled={disabled}
      onClick={() => setConfirmDone(true)}
      title="Afvinken zonder dat het dashboard de live pagina controleert"
    >
      <CheckCheck /> Gedaan zonder controle
    </Button>
  )

  let actions: React.ReactNode
  if (isIssue) {
    actions = (
      <>
        {doneButton}
        <Button size="sm" variant="ghost" className="h-7 px-2" disabled={disabled} onClick={() => void run("reject")}>
          {spin("reject", <X />)} Negeren
        </Button>
      </>
    )
  } else if (approved) {
    actions = (
      <>
        {shownValue && <CopyButton value={shownValue} onError={setError} />}
        <Button size="sm" variant="ghost" className="h-7 px-2" disabled={disabled} onClick={() => setEditing(true)}>
          <Pencil /> Bewerken
        </Button>
        {doneButton}
        <Button size="sm" variant="ghost" className="h-7 px-2" disabled={disabled} onClick={() => void run("reopen")}>
          {spin("reopen", <RotateCcw />)} Heropenen
        </Button>
      </>
    )
  } else {
    actions = (
      <>
        <Button size="sm" variant="outline" className="h-7 px-2" disabled={disabled} onClick={() => void run("approve")}>
          {spin("approve", <Check />)} Goedkeuren
        </Button>
        <Button size="sm" variant="ghost" className="h-7 px-2" disabled={disabled} onClick={() => setEditing(true)}>
          <Pencil /> Bewerken
        </Button>
        <Button size="sm" variant="ghost" className="h-7 px-2" disabled={disabled} onClick={() => void run("reject")}>
          {spin("reject", <X />)} Afwijzen
        </Button>
        {shownValue && <CopyButton value={shownValue} onError={setError} />}
      </>
    )
  }

  const hint = !item.checkable ? (
    <p className="text-xs text-muted-foreground">
      Dit punt is niet automatisch te controleren; vink het af met &ldquo;Gedaan zonder controle&rdquo;.
    </p>
  ) : null

  return (
    <li className="space-y-2 py-3">
      <div className="flex flex-wrap items-start gap-2">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2 pt-1">
          {item.severity && <SeverityBadge severity={item.severity} />}
          <p className="min-w-0 text-sm font-medium [overflow-wrap:anywhere]">{item.title}</p>
          {approved && <Pill tone="blue">Goedgekeurd</Pill>}
          {approved && item.edited && <Pill>Bewerkt</Pill>}
        </div>
        {!editing && !confirmDone && <div className="flex shrink-0 flex-wrap items-center gap-1">{actions}</div>}
      </div>

      {isIssue ? (
        <div className="space-y-2 text-sm">
          {item.description && <p className="[overflow-wrap:anywhere]">{item.description}</p>}
          {item.rationale && (
            <p className="rounded-md bg-primary/5 p-2">
              <span className="font-medium">Aanpak: </span>
              {item.rationale}
            </p>
          )}
        </div>
      ) : (
        <dl className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[5.5rem_1fr]">
          {item.current_value && (
            <>
              <dt className={label}>Huidig</dt>
              <dd className="min-w-0 whitespace-pre-wrap [overflow-wrap:anywhere] text-muted-foreground">
                {item.current_value}
              </dd>
            </>
          )}
          <dt className={label}>{approved ? "Goedgekeurd" : "Voorstel"}</dt>
          <dd className="min-w-0">
            {editing ? (
              <ValueEditor
                topic={item.topic}
                initial={shownValue ?? ""}
                onDone={() => setEditing(false)}
                onSave={(value) =>
                  // Ongewijzigd t.o.v. het voorstel: gewoon goedkeuren, zodat het niet als bewerkt telt.
                  run("approve", value === item.proposed_value ? {} : { value })
                }
              />
            ) : (
              <>
                <p className="whitespace-pre-wrap [overflow-wrap:anywhere]">{shownValue}</p>
                {sizeInfo(item.topic, shownValue) && (
                  <p className="mt-0.5 text-xs text-muted-foreground">{sizeInfo(item.topic, shownValue)}</p>
                )}
              </>
            )}
          </dd>
          {approved && item.edited && item.proposed_value && !editing && (
            <>
              <dt className={label}>Voorstel</dt>
              <dd className="min-w-0 whitespace-pre-wrap [overflow-wrap:anywhere] text-xs text-muted-foreground">
                {item.proposed_value}
              </dd>
            </>
          )}
          {item.rationale && (
            <>
              <dt className={label}>Waarom</dt>
              <dd className="min-w-0 text-xs text-muted-foreground sm:pt-0.5">{item.rationale}</dd>
            </>
          )}
        </dl>
      )}

      <RefLink href={item.ref} />
      <NotLiveNotice item={item} />
      {(isIssue || approved) && hint}
      {approved && item.reviewed_by && (
        <p className="text-xs text-muted-foreground">
          Goedgekeurd door {item.reviewed_by}
          {item.reviewed_at ? ` op ${formatDateTime(item.reviewed_at)}` : ""}
        </p>
      )}
      {confirmDone && (
        <ConfirmDone
          busy={busy === "done"}
          onCancel={() => setConfirmDone(false)}
          onConfirm={(note) => {
            void run("done", note ? { note } : {}).then((ok) => {
              if (ok) setConfirmDone(false)
            })
          }}
        />
      )}
      {error && <p className="text-xs text-red-700">{error}</p>}
    </li>
  )
}

/** Regel in het logboek GEDAAN: datum, onderwerp, oud → nieuw, wie en of het live is teruggezien. */
export function DoneRow({
  customerId,
  item,
  onChanged,
}: {
  customerId: string
  item: ChangeItem
  onChanged: (next: ChangeItem) => void
}) {
  const { busy, error, run } = useChangeAction(customerId, item, onChanged)
  const newValue = item.approved_value ?? item.proposed_value

  return (
    <li className="grid gap-x-4 gap-y-1 py-3 text-sm sm:grid-cols-[8.5rem_1fr_auto]">
      <p className="text-xs text-muted-foreground sm:pt-0.5">{formatDateTime(item.done_at)}</p>
      <div className="min-w-0 space-y-1">
        <p className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {TOPIC_LABELS[item.topic] ?? item.topic}
          </span>
          <span className="min-w-0 font-medium [overflow-wrap:anywhere]">{item.title}</span>
          {item.verified === true && <Pill tone="green">Live teruggezien</Pill>}
          {item.verified === null && <Pill>Zonder controle</Pill>}
          {item.verified === false && <Pill tone="amber">Niet teruggezien</Pill>}
        </p>
        {newValue && (
          <p className="whitespace-pre-wrap [overflow-wrap:anywhere] text-xs">
            {item.current_value && (
              <>
                <span className="text-muted-foreground line-through">{item.current_value}</span>
                <span className="px-1.5 text-muted-foreground">→</span>
              </>
            )}
            {newValue}
          </p>
        )}
        {item.note && <p className="text-xs text-muted-foreground">Notitie: {item.note}</p>}
        {item.done_by && <p className="text-xs text-muted-foreground">Door {item.done_by}</p>}
        {error && <p className="text-xs text-red-700">{error}</p>}
      </div>
      <div>
        <Button size="sm" variant="ghost" className="h-7 px-2" disabled={busy !== null} onClick={() => void run("reopen")}>
          {busy ? <Loader2 className="animate-spin" /> : <RotateCcw />} Heropenen
        </Button>
      </div>
    </li>
  )
}

/** Afgewezen voorstel of genegeerd actiepunt, met "Heropenen". */
export function RejectedRow({
  customerId,
  item,
  onChanged,
}: {
  customerId: string
  item: ChangeItem
  onChanged: (next: ChangeItem) => void
}) {
  const { busy, error, run } = useChangeAction(customerId, item, onChanged)
  const value = item.proposed_value ?? item.description

  return (
    <li className="flex items-start gap-3 py-2 text-sm">
      <div className="min-w-0 flex-1 space-y-0.5">
        <p className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {TOPIC_LABELS[item.topic] ?? item.topic}
          </span>
          <span className="min-w-0 text-muted-foreground line-through [overflow-wrap:anywhere]">{item.title}</span>
        </p>
        {value && <p className="truncate text-xs text-muted-foreground">{value}</p>}
        {item.reviewed_by && (
          <p className="text-xs text-muted-foreground">
            Afgewezen door {item.reviewed_by}
            {item.reviewed_at ? ` op ${formatDateTime(item.reviewed_at)}` : ""}
          </p>
        )}
        {error && <p className="text-xs text-red-700">{error}</p>}
      </div>
      <Button size="sm" variant="ghost" className="h-7 shrink-0 px-2" disabled={busy !== null} onClick={() => void run("reopen")}>
        {busy ? <Loader2 className="animate-spin" /> : <RotateCcw />} Heropenen
      </Button>
    </li>
  )
}
