"use client"

import Link from "next/link"
import { ChevronRight, Search } from "lucide-react"
import { useEffect, useMemo, useState } from "react"

import { Input } from "@/components/ui/input"
import { Pill, ScanStatusBadge } from "@/components/livegang/shared"
import { apiFetch, formatDateTime, type LaunchCustomer } from "@/lib/launch-checklist"

export function LivegangOverview() {
  const [customers, setCustomers] = useState<LaunchCustomer[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState("")

  useEffect(() => {
    apiFetch<{ customers: LaunchCustomer[] }>("/customers")
      .then((data) => setCustomers(data.customers))
      .catch((err: Error) => setError(err.message))
  }, [])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!customers) return []
    if (!q) return customers
    return customers.filter(
      (c) => c.name.toLowerCase().includes(q) || c.domain.toLowerCase().includes(q)
    )
  }, [customers, query])

  if (error) {
    return <p className="rounded-md border border-red-300 px-3 py-2 text-sm text-red-700">{error}</p>
  }

  return (
    <div className="space-y-4">
      <div className="relative max-w-sm">
        <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Zoek klant of domein…"
          className="pl-9"
        />
      </div>

      {customers === null ? (
        <p className="text-sm text-muted-foreground">Klanten laden…</p>
      ) : filtered.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          Geen klanten gevonden. Voeg eerst een klant met website-URL toe onder Klanten.
        </p>
      ) : (
        <ul className="divide-y rounded-lg border bg-card">
          {filtered.map((customer) => {
            const scan = customer.latest_scan
            const issues = scan?.summary_stats?.issues
            return (
              <li key={customer.id}>
                <Link
                  href={`/dashboard/livegang/${customer.id}`}
                  className="flex items-center gap-4 px-4 py-3 transition-colors hover:bg-muted/50"
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium">{customer.name}</p>
                    <p className="truncate text-sm text-muted-foreground">{customer.domain}</p>
                  </div>
                  <div className="hidden text-right text-xs text-muted-foreground sm:block">
                    {scan ? `Laatste scan: ${formatDateTime(scan.created_at)}` : "Nog niet gescand"}
                  </div>
                  <div className="flex items-center gap-2">
                    <Pill tone="blue">Fase 1</Pill>
                    {scan ? <ScanStatusBadge status={scan.status} /> : <Pill>Niet gestart</Pill>}
                    {issues && issues.total > 0 && (
                      <Pill tone={(issues.by_severity.hoog ?? 0) > 0 ? "red" : "amber"}>
                        {issues.total} actiepunten
                      </Pill>
                    )}
                  </div>
                  <ChevronRight className="size-4 text-muted-foreground" />
                </Link>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
