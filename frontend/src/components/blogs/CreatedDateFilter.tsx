"use client"

import { useRouter } from "next/navigation"
import { X } from "lucide-react"

export function CreatedDateFilter({
  selectedDay,
  scope,
  customerWebsiteId,
  basePath,
}: {
  selectedDay: string | null
  scope: string
  customerWebsiteId: string | null
  basePath: string
}) {
  const router = useRouter()

  const onChange = (day: string) => {
    const params = new URLSearchParams()
    if (scope !== "all") {
      params.set("scope", scope)
    }
    if (customerWebsiteId) {
      params.set("customer_website_id", customerWebsiteId)
    }
    if (day) {
      // Lokale daggrenzen omzetten naar UTC-instants; de server blijft
      // timezone-agnostisch.
      const start = new Date(`${day}T00:00:00`)
      const end = new Date(start)
      end.setDate(end.getDate() + 1)
      params.set("created_on", day)
      params.set("created_from", start.toISOString())
      params.set("created_to", end.toISOString())
    }
    const query = params.toString()
    router.push(query ? `${basePath}?${query}` : basePath)
  }

  return (
    <div className="flex items-center gap-1">
      <input
        type="date"
        value={selectedDay ?? ""}
        onChange={(event) => onChange(event.target.value)}
        aria-label="Filter op aanmaakdatum"
        className="h-9 rounded-md border border-input bg-background px-3 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      />
      {selectedDay && (
        <button
          type="button"
          onClick={() => onChange("")}
          aria-label="Datumfilter wissen"
          className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-input bg-background text-muted-foreground shadow-sm transition-colors hover:bg-muted"
        >
          <X className="h-4 w-4" />
        </button>
      )}
    </div>
  )
}
