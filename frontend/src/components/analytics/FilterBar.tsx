"use client"

import { X } from "lucide-react"
import { useId } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import type { AnalyticsFilters } from "@/lib/analytics/api"

export type FilterBarProps = {
  filters: AnalyticsFilters
  onChange: (patch: Partial<AnalyticsFilters>) => void
}

/**
 * Eén rij filters boven alles wat ze beïnvloeden: periode en "Alle scans". De
 * klant komt uit het adres (klantkiezer in de sidebar), niet uit deze balk.
 */
export function FilterBar({ filters, onChange }: FilterBarProps) {
  const id = useId()
  const invalidPeriod = !!filters.start && !!filters.end && filters.start > filters.end

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-end gap-3">
        <div className="w-[calc(50%-0.375rem)] space-y-1 sm:w-40">
          <label htmlFor={`${id}-van`} className="text-xs font-medium text-muted-foreground">
            Van
          </label>
          <Input
            id={`${id}-van`}
            type="date"
            value={filters.start ?? ""}
            className="bg-card"
            max={filters.end ?? undefined}
            aria-invalid={invalidPeriod || undefined}
            onChange={(e) => onChange({ start: e.target.value || null })}
          />
        </div>
        <div className="w-[calc(50%-0.375rem)] space-y-1 sm:w-40">
          <label htmlFor={`${id}-tot`} className="text-xs font-medium text-muted-foreground">
            Tot en met
          </label>
          <Input
            id={`${id}-tot`}
            type="date"
            value={filters.end ?? ""}
            className="bg-card"
            min={filters.start ?? undefined}
            aria-invalid={invalidPeriod || undefined}
            onChange={(e) => onChange({ end: e.target.value || null })}
          />
        </div>
        {(filters.start || filters.end) && (
          <Button variant="ghost" size="sm" onClick={() => onChange({ start: null, end: null })}>
            <X />
            Hele periode
          </Button>
        )}

        <label
          className="flex h-9 items-center gap-2 text-sm"
          title="Standaard telt per ronde alleen de laatste voltooide scan. Zet dit aan om ook de andere scans te zien."
        >
          <input
            type="checkbox"
            className="size-4 accent-primary"
            checked={filters.allScans}
            onChange={(e) => onChange({ allScans: e.target.checked })}
          />
          Alle scans
        </label>
      </div>
      {invalidPeriod && (
        <p role="alert" className="text-sm text-red-700 dark:text-red-400">
          De begindatum ligt na de einddatum.
        </p>
      )}
    </div>
  )
}
