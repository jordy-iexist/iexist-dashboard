"use client"

import { AlertTriangle, Check, Copy, Loader2, Pencil, Save, WandSparkles } from "lucide-react"
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react"

import { Button } from "@/components/ui/button"
import { Pill } from "@/components/livegang/shared"
import { formatDateTime, type SchemaGraphEntity, type SchemaMarkupResponse } from "@/lib/launch-checklist"
import { cn } from "@/lib/utils"

/** Gedeelde weergave van een schemavoorstel; gebruikt door de dialog voor één pagina en het bulkscherm. */

/** Eén regel schema-types als pills, met een label ervoor. */
export function TypeRow({ label, types, tone }: { label: string; types: string[]; tone: "muted" | "blue" }) {
  return (
    <div className="flex flex-wrap items-center gap-1">
      <span className="mr-1 text-xs text-muted-foreground">{label}</span>
      {types.map((t) => (
        <Pill key={t} tone={tone}>{t}</Pill>
      ))}
    </div>
  )
}

/** Plaatshouders die nog ingevuld moeten worden; niets als de lijst leeg is. */
export function SchemaPlaceholders({ placeholders }: { placeholders: string[] }) {
  if (placeholders.length === 0) return null
  return (
    <div className="space-y-1 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
      <p className="font-medium">Eerst invullen</p>
      <p className="text-xs">Vervang deze plaatshouders in het blok voordat je het plakt:</p>
      <ul className="list-disc space-y-0.5 pl-5 font-mono text-xs">
        {placeholders.map((p) => (
          <li key={p} className="break-all">{p}</li>
        ))}
      </ul>
    </div>
  )
}

/** Validatieproblemen van het voorstel; niets als de lijst leeg is. */
export function SchemaProblems({ problems }: { problems: string[] }) {
  if (problems.length === 0) return null
  return (
    <div className="space-y-1 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-900 dark:border-red-800 dark:bg-red-950/40 dark:text-red-200">
      <p className="flex items-center gap-1.5 font-medium">
        <AlertTriangle className="size-4 shrink-0" /> Controleer vóór plaatsen
      </p>
      <ul className="list-disc space-y-0.5 pl-5 text-xs">
        {problems.map((p, i) => (
          <li key={i}>{p}</li>
        ))}
      </ul>
    </div>
  )
}

/** Standaardtypes van Rank Math die bij plaatsen vervallen, als amber pills. */
export function ReplacedDefaultTypes({ types }: { types: string[] }) {
  return (
    <div className="flex flex-wrap gap-1">
      {types.map((t) => (
        <Pill key={t} tone="amber">{t}</Pill>
      ))}
    </div>
  )
}

/** Voor welke types het voorstel is gemaakt, en of dat een eigen keuze of automatisch is. */
export function SchemaTargetInfo({ result }: { result: SchemaMarkupResponse }) {
  const types = result.target_types ?? []
  if (types.length === 0) return null
  return (
    <div className="flex flex-wrap items-center gap-1">
      <span className="mr-1 text-xs text-muted-foreground">Gemaakt voor:</span>
      {types.map((t) => (
        <Pill key={t}>{t.replace("|", " / ")}</Pill>
      ))}
      {result.target_types_source && (
        <span className="ml-1 text-xs text-muted-foreground">
          ({result.target_types_source === "manual" ? "eigen keuze" : "automatisch"})
        </span>
      )}
    </div>
  )
}

/** De typekeuze is na het maken van dit voorstel gewijzigd; niets als dat niet zo is. */
export function SchemaStaleNotice({ stale }: { stale?: boolean }) {
  if (!stale) return null
  return (
    <div className="flex items-start gap-1.5 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
      <AlertTriangle className="mt-0.5 size-4 shrink-0" />
      <p>
        De schema-types voor deze pagina zijn gewijzigd nadat dit voorstel is gemaakt. Genereer opnieuw om een voorstel
        voor de nieuwe keuze te krijgen.
      </p>
    </div>
  )
}

/** Aanbevolen eigenschappen die niet in te vullen waren ("Type.eigenschap"), gegroepeerd per type. */
export function SchemaOmitted({ omitted }: { omitted?: string[] }) {
  if (!omitted || omitted.length === 0) return null
  const groups = new Map<string, string[]>()
  for (const item of omitted) {
    const dot = item.indexOf(".")
    const type = dot > 0 ? item.slice(0, dot) : ""
    const prop = dot > 0 ? item.slice(dot + 1) : item
    groups.set(type, [...(groups.get(type) ?? []), prop])
  }
  return (
    <div className="space-y-0.5 text-xs text-muted-foreground">
      <p>Niet gevonden op de pagina, daarom weggelaten:</p>
      <ul className="space-y-0.5 pl-3">
        {[...groups.entries()].map(([type, props]) => (
          <li key={type || "_"}>
            {type && <span className="font-medium">{type}: </span>}
            <span className="font-mono">{props.join(", ")}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

const ENTITY_STATUS: Record<SchemaGraphEntity["status"], { label: string; tone: "muted" | "blue" | "amber" }> = {
  existing: { label: "bestaand", tone: "muted" },
  new: { label: "NIEUW", tone: "blue" },
  lapses: { label: "vervalt", tone: "amber" },
}

/** Zoveel eigenschappen direct tonen; de rest achter "meer". */
const VISIBLE_PROPERTIES = 8

function GraphEntity({ entity }: { entity: SchemaGraphEntity }) {
  const [expanded, setExpanded] = useState(false)
  const status = ENTITY_STATUS[entity.status] ?? ENTITY_STATUS.existing
  const props = entity.properties ?? []
  const shown = expanded ? props : props.slice(0, VISIBLE_PROPERTIES)
  const hidden = props.length - shown.length
  return (
    <li
      className={cn(
        "space-y-1 rounded-md border px-2.5 py-1.5",
        entity.status === "new" && "border-blue-300 bg-blue-50/60 dark:border-blue-800 dark:bg-blue-950/30",
        entity.status === "lapses" && "border-amber-300 bg-amber-50/60 dark:border-amber-800 dark:bg-amber-950/30"
      )}
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <span className={cn("text-sm font-medium", entity.status === "lapses" && "line-through decoration-amber-600/60")}>
          {entity.types.join(" + ") || "(zonder type)"}
        </span>
        <Pill tone={status.tone} className={cn(entity.status === "new" && "font-semibold")}>
          {status.label}
        </Pill>
        {entity.id && (
          <span className="min-w-0 truncate font-mono text-[11px] text-muted-foreground" title={entity.id}>
            {entity.id}
          </span>
        )}
      </div>
      {props.length > 0 && (
        <p className="font-mono text-[11px] leading-relaxed text-muted-foreground">
          {shown.join(", ")}
          {hidden > 0 && (
            <>
              {", "}
              <button
                type="button"
                className="font-sans text-primary hover:underline"
                onClick={() => setExpanded(true)}
                aria-label={`Nog ${hidden} eigenschappen tonen`}
              >
                +{hidden} meer
              </button>
            </>
          )}
          {expanded && props.length > VISIBLE_PROPERTIES && (
            <>
              {" "}
              <button type="button" className="font-sans text-primary hover:underline" onClick={() => setExpanded(false)}>
                minder
              </button>
            </>
          )}
        </p>
      )}
    </li>
  )
}

/**
 * De entiteiten van de pagina zoals die na plaatsen worden (bestaand, nieuw, vervalt). Zonder `page_graph`
 * (oud voorstel of oude backend) de eenvoudige regels met bestaande en nieuwe types.
 */
export function SchemaEntities({ result }: { result: SchemaMarkupResponse }) {
  const graph = result.page_graph ?? []
  if (graph.length === 0) {
    return (
      <>
        {/* Het blok bevat alleen wat ontbrak; zonder deze regel lijkt het de complete markup. */}
        {(result.existing_types ?? []).length > 0 && (
          <TypeRow label="Staat al op de pagina (niet herhaald):" types={result.existing_types} tone="muted" />
        )}
        {result.types.length > 0 && <TypeRow label="Nieuw in dit blok:" types={result.types} tone="blue" />}
      </>
    )
  }
  const counts = { existing: 0, new: 0, lapses: 0 }
  for (const e of graph) counts[e.status] = (counts[e.status] ?? 0) + 1
  return (
    <div className="space-y-1.5">
      <p className="text-xs text-muted-foreground">
        Schema van de pagina na plaatsen: {counts.new} nieuw, {counts.existing} bestaand
        {counts.lapses > 0 ? `, ${counts.lapses} vervalt` : ""}.
      </p>
      <ul className="space-y-1">
        {graph.map((entity, i) => (
          <GraphEntity key={`${entity.id ?? ""}-${i}`} entity={entity} />
        ))}
      </ul>
    </div>
  )
}

type ScriptView = "new" | "full"

/** De JSON van een `<script type="application/ld+json">`-blok, zonder het omhulsel. */
export function scriptToJson(script: string): string {
  const match = /^\s*<script\b[^>]*>([\s\S]*?)<\/script>\s*$/i.exec(script)
  return (match ? match[1] : script).trim()
}

type JsonIssue = { message: string; line: number; column: number }

class JsonFail {
  constructor(
    readonly message: string,
    readonly at: number
  ) {}
}

const NUMBER_PATTERN = /-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/y

/**
 * Controleert of `text` geldige JSON is en geeft anders de eerste fout met regel en kolom (vanaf 1).
 * Eigen controle i.p.v. `JSON.parse`: niet elke browser noemt de plek van de fout in zijn melding.
 */
export function checkJson(text: string): JsonIssue | null {
  let i = 0
  const n = text.length
  const fail = (message: string, at = i): never => {
    throw new JsonFail(message, at)
  }
  const describe = (at: number) =>
    at >= n ? "het einde van de tekst" : text[at] === '"' ? "een aanhalingsteken" : `"${text[at]}"`
  const skipSpace = () => {
    while (i < n && (text[i] === " " || text[i] === "\t" || text[i] === "\n" || text[i] === "\r")) i++
  }

  function string() {
    const start = i
    i++
    while (i < n) {
      const c = text[i]
      if (c === '"') {
        i++
        return
      }
      if (c === "\\") {
        const next = text[i + 1]
        if (next !== undefined && '"\\/bfnrt'.includes(next)) i += 2
        else if (next === "u" && /^[0-9a-fA-F]{4}$/.test(text.slice(i + 2, i + 6))) i += 6
        else fail("Ongeldige escape (\\) in een tekst")
        continue
      }
      if (c === "\n" || c === "\r") fail("Tekst niet afgesloten met een dubbel aanhalingsteken vóór het einde van de regel")
      if (c.charCodeAt(0) < 0x20) fail("Ongeldig stuurteken (bijvoorbeeld een tab) in een tekst; gebruik \\t")
      i++
    }
    fail("Tekst niet afgesloten met een dubbel aanhalingsteken", start)
  }

  function value(): void {
    skipSpace()
    if (i >= n) fail("Onverwacht einde van de tekst; er ontbreekt een waarde")
    const c = text[i]
    if (c === "{") return container("}")
    if (c === "[") return container("]")
    if (c === '"') return string()
    if (c === "-" || (c >= "0" && c <= "9")) {
      NUMBER_PATTERN.lastIndex = i
      const match = NUMBER_PATTERN.exec(text)
      if (!match) return fail("Ongeldig getal")
      i += match[0].length
      return
    }
    for (const word of ["true", "false", "null"]) {
      if (text.startsWith(word, i)) {
        i += word.length
        return
      }
    }
    if (c === "'") fail("Gebruik dubbele aanhalingstekens (\") in plaats van enkele")
    fail(`Onverwacht teken ${describe(i)}; hier hoort een waarde`)
  }

  function container(close: "}" | "]") {
    const isObject = close === "}"
    i++
    skipSpace()
    if (text[i] === close) {
      i++
      return
    }
    for (;;) {
      skipSpace()
      if (isObject) {
        if (text[i] === close) fail(`Komma te veel vóór "${close}"`)
        if (text[i] !== '"') {
          fail(
            text[i] === "'"
              ? "Gebruik dubbele aanhalingstekens (\") in plaats van enkele"
              : `Verwacht een eigenschapsnaam tussen dubbele aanhalingstekens, niet ${describe(i)}`
          )
        }
        string()
        skipSpace()
        if (text[i] !== ":") fail(`Verwacht ":" na de eigenschapsnaam, niet ${describe(i)}`)
        i++
      } else if (text[i] === close) {
        fail(`Komma te veel vóór "${close}"`)
      }
      value()
      skipSpace()
      if (text[i] === ",") {
        i++
        continue
      }
      if (text[i] === close) {
        i++
        return
      }
      if (i < n && (isObject ? text[i] === '"' : '"{['.includes(text[i]))) {
        fail(`Komma ontbreekt tussen twee ${isObject ? "eigenschappen" : "waarden"}`)
      }
      fail(`Verwacht "," of "${close}", niet ${describe(i)}`)
    }
  }

  try {
    skipSpace()
    if (i >= n) fail("Het blok is leeg")
    value()
    skipSpace()
    if (i < n) fail(`Extra tekst na het einde van de JSON: ${describe(i)}`)
    return null
  } catch (err) {
    if (!(err instanceof JsonFail)) throw err
    const before = text.slice(0, err.at)
    const line = before.split("\n").length
    const column = err.at - (before.lastIndexOf("\n") + 1) + 1
    return { message: err.message, line, column }
  }
}

/** Stand van het bewerken, voor de dialog (knoppen uitschakelen, wegnavigeren bevestigen). */
export type SchemaEditState = { editing: boolean; dirty: boolean }

const TEXTAREA_INDENT = "  "

/**
 * Bewerkstand van het nieuwe blok: een tekstvak met de JSON, controle tijdens het typen, "Opmaken",
 * "Opslaan" en "Annuleren" (met bevestiging als er niet-opgeslagen wijzigingen zijn).
 */
function SchemaEditor({
  initial,
  onSave,
  onDone,
  onDirtyChange,
}: {
  initial: string
  onSave: (jsonld: string) => Promise<SchemaMarkupResponse>
  onDone: () => void
  onDirtyChange: (dirty: boolean) => void
}) {
  const [draft, setDraft] = useState(initial)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [confirmCancel, setConfirmCancel] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const issue = useMemo(() => checkJson(draft), [draft])
  const dirty = draft !== initial

  const dirtyRef = useRef(onDirtyChange)
  useEffect(() => {
    dirtyRef.current = onDirtyChange
  })
  useEffect(() => {
    dirtyRef.current(dirty)
  }, [dirty])

  useEffect(() => {
    textareaRef.current?.focus({ preventScroll: true })
  }, [])

  function update(next: string) {
    setDraft(next)
    setSaveError(null)
    setConfirmCancel(false)
  }

  function onKeyDown(ev: KeyboardEvent<HTMLTextAreaElement>) {
    if (ev.key !== "Tab" || ev.shiftKey || ev.altKey || ev.ctrlKey || ev.metaKey || saving) return
    ev.preventDefault()
    const el = ev.currentTarget
    // insertText behoudt "ongedaan maken"; anders zelf invoegen en de cursor terugzetten.
    if (document.execCommand("insertText", false, TEXTAREA_INDENT)) return
    const { selectionStart, selectionEnd } = el
    update(draft.slice(0, selectionStart) + TEXTAREA_INDENT + draft.slice(selectionEnd))
    requestAnimationFrame(() => {
      el.selectionStart = el.selectionEnd = selectionStart + TEXTAREA_INDENT.length
    })
  }

  function format() {
    try {
      update(JSON.stringify(JSON.parse(draft), null, 2))
    } catch {
      // Opmaken is alleen beschikbaar bij geldige JSON.
    }
  }

  async function save() {
    if (issue || !dirty || saving) return
    setSaving(true)
    setSaveError(null)
    try {
      await onSave(draft)
      onDone()
    } catch (err) {
      setSaveError((err as Error).message || "Opslaan is mislukt.")
      setSaving(false)
    }
  }

  function cancel() {
    if (dirty) setConfirmCancel(true)
    else onDone()
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm font-medium">Nieuw blok bewerken</p>
        <Button
          size="sm"
          variant="ghost"
          className="ml-auto h-7 px-2"
          disabled={!!issue || saving}
          onClick={format}
          title="Springt de JSON netjes in (2 spaties)"
        >
          <WandSparkles /> Opmaken
        </Button>
      </div>

      <textarea
        ref={textareaRef}
        value={draft}
        onChange={(ev) => update(ev.target.value)}
        onKeyDown={onKeyDown}
        readOnly={saving}
        spellCheck={false}
        autoCapitalize="off"
        autoCorrect="off"
        autoComplete="off"
        wrap="off"
        aria-label="JSON van het nieuwe blok"
        aria-invalid={!!issue}
        aria-describedby="schema-editor-status"
        className={cn(
          "block h-[55dvh] min-h-64 w-full resize-y overflow-auto rounded-md border bg-background p-3 font-mono text-xs leading-relaxed outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
          issue && "border-red-400 dark:border-red-800",
          saving && "opacity-70"
        )}
      />

      <div id="schema-editor-status" className="space-y-1 text-xs">
        {issue ? (
          <p className="flex items-start gap-1.5 text-red-700 dark:text-red-400">
            <AlertTriangle className="mt-px size-3.5 shrink-0" />
            <span>
              Ongeldige JSON op regel {issue.line}, kolom {issue.column}: {issue.message}.
            </span>
          </p>
        ) : (
          <p className="flex items-center gap-1.5 text-green-700 dark:text-green-400">
            <Check className="size-3.5 shrink-0" /> Geldige JSON
          </p>
        )}
        <p className="text-muted-foreground">
          Alleen de JSON, zonder &lt;script&gt;-tags. Tab voegt twee spaties in. Na opslaan worden types, plaatshouders
          en problemen opnieuw berekend; een eerdere goedkeuring vervalt.
        </p>
        {saveError && <p className="text-sm text-red-600">{saveError}</p>}
      </div>

      {confirmCancel ? (
        <div className="space-y-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
          <p className="font-medium">Wijzigingen weggooien?</p>
          <p className="text-xs">De aanpassingen in het blok zijn nog niet opgeslagen en gaan verloren.</p>
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
          <Button size="sm" variant="outline" disabled={saving} onClick={cancel}>
            Annuleren
          </Button>
          <Button
            size="sm"
            disabled={!!issue || !dirty || saving}
            onClick={() => void save()}
            title={issue ? "Herstel eerst de JSON-fout" : !dirty ? "Nog niets gewijzigd" : undefined}
          >
            {saving ? <Loader2 className="animate-spin" /> : <Save />} {saving ? "Opslaan…" : "Opslaan"}
          </Button>
        </div>
      )}
    </div>
  )
}

/** Kenmerk dat het nieuwe blok handmatig is bewerkt, met de datum; niets als dat niet zo is. */
export function SchemaEditedBadge({ result }: { result: SchemaMarkupResponse }) {
  if (!result.edited) return null
  return (
    <Pill tone="amber" className="gap-1">
      <Pencil className="size-3" /> Handmatig bewerkt{result.edited_at ? ` op ${formatDateTime(result.edited_at)}` : ""}
    </Pill>
  )
}

/**
 * Het codeblok met een schakelaar tussen het nieuwe blok en de volledige pagina na plaatsen, en de knop
 * "Kopieer volledig" voor de Rich Results Test. Het nieuwe blok kopiëren blijft de taak van de dialog.
 * Met `onSave` kan het nieuwe blok ook handmatig bewerkt worden; de dialog slaat op en neemt het resultaat
 * over. `onEditStateChange` meldt of er bewerkt wordt en of er niet-opgeslagen wijzigingen zijn.
 */
export function SchemaScriptView({
  result,
  preClassName,
  onSave,
  editDisabled,
  onEditStateChange,
}: {
  result: SchemaMarkupResponse
  preClassName?: string
  onSave?: (jsonld: string) => Promise<SchemaMarkupResponse>
  /** Bewerken (tijdelijk) niet starten, bijvoorbeeld tijdens een lopende aanvraag. */
  editDisabled?: boolean
  onEditStateChange?: (state: SchemaEditState) => void
}) {
  // Standaard de complete markup van de pagina; zonder die gegevens valt het terug op het nieuwe blok.
  const [view, setView] = useState<ScriptView>("full")
  const [copied, setCopied] = useState(false)
  const [copyError, setCopyError] = useState(false)
  /** De JSON waarmee het bewerken begon; null = niet aan het bewerken. */
  const [editing, setEditing] = useState<string | null>(null)
  const [dirty, setDirty] = useState(false)
  const full = (result.full_script ?? "").trim()
  const effective: ScriptView = full ? view : "new"

  const reportRef = useRef(onEditStateChange)
  useEffect(() => {
    reportRef.current = onEditStateChange
  })
  const isEditing = editing !== null
  useEffect(() => {
    reportRef.current?.({ editing: isEditing, dirty: isEditing && dirty })
  }, [isEditing, dirty])
  // Bij weggaan (andere pagina, dialog dicht) is er niets meer in bewerking.
  useEffect(() => () => reportRef.current?.({ editing: false, dirty: false }), [])

  function startEdit() {
    // Bewerken gaat altijd over het nieuwe blok: dat is wat naar de site gaat.
    setView("new")
    setDirty(false)
    setEditing(scriptToJson(result.script))
  }

  function stopEdit() {
    setEditing(null)
    setDirty(false)
  }

  if (onSave && editing !== null) {
    return (
      <div className="space-y-1.5">
        <SchemaEditor initial={editing} onSave={onSave} onDone={stopEdit} onDirtyChange={setDirty} />
      </div>
    )
  }

  async function copyFull() {
    try {
      await navigator.clipboard.writeText(full)
      setCopyError(false)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      setCopyError(true)
    }
  }

  const editButton = onSave ? (
    <Button
      size="sm"
      variant="outline"
      className="h-7 shrink-0 px-2"
      disabled={editDisabled}
      onClick={startEdit}
      title="Het nieuwe blok handmatig aanpassen; dat is wat naar de site gaat"
    >
      <Pencil /> Bewerken
    </Button>
  ) : null

  return (
    <div className="space-y-1.5">
      {result.edited && (
        <div>
          <SchemaEditedBadge result={result} />
        </div>
      )}
      {full ? (
        <div className="flex flex-wrap items-center gap-2">
          <div role="group" aria-label="Weergave van de markup" className="inline-flex rounded-md border p-0.5 text-xs">
            {(
              [
                ["new", "Nieuw blok"],
                ["full", "Volledige pagina na plaatsen"],
              ] as const
            ).map(([key, label]) => (
              <button
                key={key}
                type="button"
                aria-pressed={effective === key}
                onClick={() => setView(key)}
                className={cn(
                  "rounded px-2 py-1",
                  effective === key ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted"
                )}
              >
                {label}
              </button>
            ))}
          </div>
          <span className="ml-auto" />
          {editButton}
          <Button
            size="sm"
            variant="ghost"
            className="h-7 px-2"
            onClick={() => void copyFull()}
            title="Voor de Rich Results Test van Google; niet op de site plakken"
          >
            {copied ? <Check /> : <Copy />} {copied ? "Gekopieerd" : "Kopieer volledig"}
          </Button>
        </div>
      ) : (
        <div className="flex items-start gap-2">
          <p className="flex-1 text-xs text-muted-foreground">
            Alleen het nieuwe blok is beschikbaar. Genereer opnieuw om ook de volledige markup van de pagina na plaatsen
            te zien.
          </p>
          {editButton}
        </div>
      )}

      <pre
        className={cn(
          "overflow-auto whitespace-pre-wrap break-words rounded-md border bg-muted/30 p-3 font-mono text-xs",
          effective === "full" && "border-dashed",
          preClassName
        )}
      >
        {effective === "full" ? full : result.script}
      </pre>

      <p className="text-xs font-medium">
        {effective === "full"
          ? "Dit is de complete markup zoals de pagina die na plaatsen heeft. Alleen het nieuwe blok gaat naar de site; de rest staat er al."
          : "Alleen dit nieuwe blok gaat naar de site; de rest van het schema staat er al."}
      </p>
      {full && (
        <p className="text-xs text-muted-foreground">
          &quot;Kopieer volledig&quot; is bedoeld om in de Rich Results Test te plakken, niet op de site: dan staat het
          bestaande schema er dubbel.
        </p>
      )}
      {copyError && <p className="text-xs text-red-600">Kopiëren naar het klembord is mislukt.</p>}
    </div>
  )
}
