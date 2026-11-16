"use client"

import { X } from "lucide-react"
import { useId, useMemo } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import type { AnalyticsFilters } from "@/lib/analytics/api"
import type { LaunchCustomer } from "@/lib/launch-checklist"

const selectClass =
  "h-9 w-full min-w-0 rounded-md border border-input bg-transparent px-3 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 dark:bg-input/30"

export type FilterBarProps = {
  /** `null` zolang de klanten laden. */
  customers: LaunchCustomer[] | null
  filters: AnalyticsFilters
  onChange: (patch: Partial<AnalyticsFilters>) => void
  /** Periode (van/tot) tonen. */
  showPeriod?: boolean
  /** Schakelaar "Alle scans" tonen. */
  showAllScans?: boolean
  /** Toont de keuze "Alle klanten" in de klantkiezer; die roept dit aan i.p.v. `onChange`. */
  onAllCustomers?: () => void
}

const ALL_CUSTOMERS = "__alle_klanten__"

function hasScans(customer: LaunchCustomer): boolean {
  return !!(customer.latest_scan || customer.latest_quarterly_scan)
}

/** Eén rij filters boven alles wat ze beïnvloeden: klant, periode en "Alle scans". */
export function FilterBar({
  customers,
  filters,
  onChange,
  showPeriod = true,
  showAllScans = true,
  onAllCustomers,
}: FilterBarProps) {
  const id = useId()
  const sorted = useMemo(
    () => (customers ? [...customers].sort((a, b) => a.name.localeCompare(b.name, "nl")) : []),
    [customers]
  )
  const unknownCustomer = !!filters.customerId && !!customers && !customers.some((c) => c.id === filters.customerId)
  const invalidPeriod = !!filters.start && !!filters.end && filters.start > filters.end

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-end gap-3">
        <div className="w-full space-y-1 sm:w-72">
          <label htmlFor={`${id}-klant`} className="text-xs font-medium text-muted-foreground">
            Klant
          </label>
          <select
            id={`${id}-klant`}
            className={selectClass}
            value={filters.customerId ?? ""}
            disabled={customers === null}
            onChange={(e) =>
              e.target.value === ALL_CUSTOMERS ? onAllCustomers?.() : onChange({ customerId: e.target.value || null })
            }
          >
            <option value="">{customers === null ? "Klanten laden…" : "Kies een klant…"}</option>
            {onAllCustomers && <option value={ALL_CUSTOMERS}>Alle klanten vergelijken…</option>}
            {unknownCustomer && <option value={filters.customerId ?? ""}>Onbekende klant</option>}
            {sorted.map((customer) => (
              <option key={customer.id} value={customer.id}>
                {customer.name}
                {hasScans(customer) ? "" : " (nog niet gescand)"}
              </option>
            ))}
          </select>
        </div>

        {showPeriod && (
          <>
            <div className="w-[calc(50%-0.375rem)] space-y-1 sm:w-40">
              <label htmlFor={`${id}-van`} className="text-xs font-medium text-muted-foreground">
                Van
              </label>
              <Input
                id={`${id}-van`}
                type="date"
                value={filters.start ?? ""}
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
          </>
        )}

        {showAllScans && (
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
        )}
      </div>
      {invalidPeriod && (
        <p role="alert" className="text-sm text-red-700 dark:text-red-400">
          De begindatum ligt na de einddatum.
        </p>
      )}
    </div>
  )
}
