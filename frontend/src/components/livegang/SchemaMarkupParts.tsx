"use client"

import { AlertTriangle } from "lucide-react"

import { Pill } from "@/components/livegang/shared"

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
