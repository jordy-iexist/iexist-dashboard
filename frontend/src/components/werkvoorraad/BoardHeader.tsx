"use client"

import { Plus, RefreshCw, X } from "lucide-react"

import { selectClass } from "@/components/klanten/analyses/form-controls"
import { Button } from "@/components/ui/button"
import {
  KINDS,
  SOURCE_LABELS,
  UNASSIGNED,
  isWorkKind,
  type BoardFilters,
  type WorkBoardCustomer,
  type WorkBoardUser,
} from "@/lib/work-queue"
import { cn } from "@/lib/utils"

const pillSelect = cn(selectClass, "h-8 w-auto max-w-[220px] rounded-full pr-8 text-sm")

function plural(count: number, one: string, many: string) {
  return `${count} ${count === 1 ? one : many}`
}

/** Kop van het bord: titel, telling, filters, verversen en "+ Taak". */
export function BoardHeader({
  filters,
  openCount,
  customerCount,
  customers,
  users,
  currentUserId,
  refreshing,
  onFiltersChange,
  onRefresh,
  onNewTask,
}: {
  filters: BoardFilters
  openCount: number | null
  customerCount: number | null
  customers: WorkBoardCustomer[]
  users: WorkBoardUser[]
  currentUserId: string | null
  refreshing: boolean
  onFiltersChange: (patch: Partial<Pick<BoardFilters, "customerId" | "assigneeId" | "kind" | "source">>) => void
  onRefresh: () => void
  onNewTask: () => void
}) {
  const otherUsers = users.filter((user) => user.id !== currentUserId)
  const unknownCustomer = filters.customerId && !customers.some((customer) => customer.id === filters.customerId)
  const knownAssignee =
    !filters.assigneeId ||
    filters.assigneeId === UNASSIGNED ||
    filters.assigneeId === currentUserId ||
    users.some((user) => user.id === filters.assigneeId)

  return (
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0 space-y-1">
        <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">Bureau</p>
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Werkvoorraad</h1>
        <p className="max-w-3xl text-sm text-muted-foreground">
          {openCount !== null && customerCount !== null && (
            <>
              {plural(openCount, "taak", "taken")} over {plural(customerCount, "klant", "klanten")}
              {" · "}
            </>
          )}
          taken komen automatisch uit de SEO/GEO-scan, concurrentieanalyses, Search Console en Aanpassingen
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {filters.source && (
          <button
            type="button"
            onClick={() => onFiltersChange({ source: null })}
            className="inline-flex h-8 items-center gap-1 rounded-full border bg-card px-3 text-sm outline-none hover:bg-muted focus-visible:ring-[3px] focus-visible:ring-ring/50"
            aria-label={`Filter op bron ${SOURCE_LABELS[filters.source]} wissen`}
          >
            Bron: {SOURCE_LABELS[filters.source]}
            <X className="size-3.5 text-muted-foreground" aria-hidden />
          </button>
        )}

        <select
          aria-label="Klant"
          className={pillSelect}
          value={filters.customerId ?? ""}
          onChange={(event) => onFiltersChange({ customerId: event.target.value || null })}
        >
          <option value="">Alle klanten</option>
          {unknownCustomer && <option value={filters.customerId!}>Onbekende klant</option>}
          {customers.map((customer) => (
            <option key={customer.id} value={customer.id}>
              {customer.name}
            </option>
          ))}
        </select>

        <select
          aria-label="Specialist"
          className={pillSelect}
          value={filters.assigneeId ?? ""}
          onChange={(event) => onFiltersChange({ assigneeId: event.target.value || null })}
        >
          <option value="">Alle specialisten</option>
          <option value={UNASSIGNED}>Niet toegewezen</option>
          {currentUserId && <option value={currentUserId}>Mijn taken</option>}
          {!knownAssignee && <option value={filters.assigneeId!}>Onbekende medewerker</option>}
          {otherUsers.length > 0 && (
            <optgroup label="Specialisten">
              {otherUsers.map((user) => (
                <option key={user.id} value={user.id}>
                  {user.name}
                </option>
              ))}
            </optgroup>
          )}
        </select>

        <select
          aria-label="Soort"
          className={pillSelect}
          value={filters.kind ?? ""}
          onChange={(event) => {
            const value = event.target.value
            onFiltersChange({ kind: isWorkKind(value) ? value : null })
          }}
        >
          <option value="">Alle soorten</option>
          {KINDS.map((kind) => (
            <option key={kind.value} value={kind.value}>
              {kind.label}
            </option>
          ))}
        </select>

        <Button
          type="button"
          variant="outline"
          size="icon-sm"
          onClick={onRefresh}
          disabled={refreshing}
          aria-label="Verversen"
          title="Verversen"
        >
          <RefreshCw className={cn(refreshing && "animate-spin")} aria-hidden />
        </Button>

        <Button type="button" size="sm" onClick={onNewTask}>
          <Plus aria-hidden />
          Taak
        </Button>
      </div>
    </header>
  )
}
