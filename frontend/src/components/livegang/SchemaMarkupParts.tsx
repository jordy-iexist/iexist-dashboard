"use client"

import { AlertTriangle, Check, Copy } from "lucide-react"
import { useState } from "react"

import { Button } from "@/components/ui/button"
import { Pill } from "@/components/livegang/shared"
import type { SchemaGraphEntity, SchemaMarkupResponse } from "@/lib/launch-checklist"
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

/**
 * Het codeblok met een schakelaar tussen het nieuwe blok en de volledige pagina na plaatsen, en de knop
 * "Kopieer volledig" voor de Rich Results Test. Het nieuwe blok kopiëren blijft de taak van de dialog.
 */
export function SchemaScriptView({ result, preClassName }: { result: SchemaMarkupResponse; preClassName?: string }) {
  const [view, setView] = useState<ScriptView>("new")
  const [copied, setCopied] = useState(false)
  const [copyError, setCopyError] = useState(false)
  const full = (result.full_script ?? "").trim()
  const effective: ScriptView = full ? view : "new"

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

  return (
    <div className="space-y-1.5">
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
          <Button
            size="sm"
            variant="ghost"
            className="ml-auto h-7 px-2"
            onClick={() => void copyFull()}
            title="Voor de Rich Results Test van Google; niet op de site plakken"
          >
            {copied ? <Check /> : <Copy />} {copied ? "Gekopieerd" : "Kopieer volledig"}
          </Button>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">
          Alleen het nieuwe blok is beschikbaar. Genereer opnieuw om ook de volledige markup van de pagina na plaatsen te
          zien.
        </p>
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
