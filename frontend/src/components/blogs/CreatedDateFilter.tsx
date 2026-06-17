"use client"

import { useRouter } from "next/navigation"
import { X } from "lucide-react"

import { BLOGS_CREATED_DATE_COOKIE } from "@/lib/blogs-date-filter"

// 7 dagen, in dezelfde stijl als de sidebar-cookie.
const COOKIE_MAX_AGE = 60 * 60 * 24 * 7

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
      const createdFrom = start.toISOString()
      const createdTo = end.toISOString()
      params.set("created_on", day)
      params.set("created_from", createdFrom)
      params.set("created_to", createdTo)
      // Selectie onthouden over routes heen totdat de gebruiker hem wist.
      const value = encodeURIComponent(
        JSON.stringify({ createdOn: day, createdFrom, createdTo })
      )
      document.cookie = `${BLOGS_CREATED_DATE_COOKIE}=${value}; path=/; max-age=${COOKIE_MAX_AGE}`
    } else {
      document.cookie = `${BLOGS_CREATED_DATE_COOKIE}=; path=/; max-age=0`
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
