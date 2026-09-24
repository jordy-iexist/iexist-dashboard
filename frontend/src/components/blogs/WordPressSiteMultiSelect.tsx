"use client"

import { useMemo, useState } from "react"
import { ChevronDown } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { WordPressSite } from "@/lib/wordpress-types"

const SEARCH_THRESHOLD = 6

type WordPressSiteMultiSelectProps = {
  sites: WordPressSite[]
  selectedIds: string[]
  onToggle: (siteId: string, checked: boolean) => void
  disabled?: boolean
}

export function WordPressSiteMultiSelect({
  sites,
  selectedIds,
  onToggle,
  disabled,
}: WordPressSiteMultiSelectProps) {
  const [query, setQuery] = useState("")

  const filteredSites = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return sites
    return sites.filter((site) => site.name.toLowerCase().includes(needle))
  }, [sites, query])

  const label =
    selectedIds.length === 0
      ? "Kies WordPress sites"
      : selectedIds.length === 1
        ? sites.find((site) => site.id === selectedIds[0])?.name ?? "1 site geselecteerd"
        : `${selectedIds.length} sites geselecteerd`

  return (
    <Popover onOpenChange={(open) => !open && setQuery("")}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          disabled={disabled}
          className="max-w-full justify-between"
        >
          <span className="truncate">{label}</span>
          <ChevronDown className="text-muted-foreground" />
        </Button>
      </PopoverTrigger>
      <PopoverContent>
        {sites.length > SEARCH_THRESHOLD && (
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Zoek site..."
            className="mb-2 w-full rounded-md border bg-background px-2 py-1 text-sm"
          />
        )}
        <div className="max-h-64 space-y-0.5 overflow-y-auto">
          {filteredSites.length === 0 ? (
            <p className="px-2 py-1.5 text-sm text-muted-foreground">Geen sites gevonden.</p>
          ) : (
            filteredSites.map((site) => (
              <label
                key={site.id}
                className="flex cursor-pointer items-center gap-2 rounded-sm px-2 py-1.5 text-sm hover:bg-accent"
              >
                <input
                  type="checkbox"
                  checked={selectedIds.includes(site.id)}
                  onChange={(event) => onToggle(site.id, event.target.checked)}
                  disabled={disabled}
                />
                <span className="truncate">{site.name}</span>
              </label>
            ))
          )}
        </div>
      </PopoverContent>
    </Popover>
  )
}
