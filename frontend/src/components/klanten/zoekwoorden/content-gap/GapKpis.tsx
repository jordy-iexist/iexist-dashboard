import { formatInt } from "@/components/klanten/analyses/result-parts"
import { KpiCard } from "@/components/klanten/dashboard/KpiCard"
import { Pill } from "@/components/livegang/shared"
import type { ContentGapOverview } from "@/lib/keyword-content-gap"

/** Gezamenlijk zoekvolume van de uitgewerkte zoekwoorden (onbekend telt als 0). */
export function totalVolume(overview: ContentGapOverview) {
  return overview.keywords.reduce((sum, keyword) => sum + (keyword.volume ?? 0), 0)
}

/**
 * De vier tegels boven de tabel. "Relevant na AI-filter" en "Onderwerpen" komen in een volgende
 * stap; tot die tijd "—" met "Binnenkort".
 */
export function GapKpis({ overview }: { overview: ContentGapOverview }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <KpiCard
        label="Gap-zoekwoorden"
        value={formatInt(overview.found)}
        hint={`${formatInt(overview.keywords.length)} uitgewerkt · uit Ahrefs`}
      />
      <KpiCard label="Relevant na AI-filter" value="—" hint={<Pill>Binnenkort</Pill>} />
      <KpiCard
        label="Gezamenlijk volume"
        value={`${formatInt(totalVolume(overview))} /mnd`}
        tone="good"
        hint="van de uitgewerkte zoekwoorden"
      />
      <KpiCard label="Onderwerpen" value="—" hint={<Pill>Binnenkort</Pill>} />
    </div>
  )
}
