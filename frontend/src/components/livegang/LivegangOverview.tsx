"use client"

import Link from "next/link"
import { ChevronRight, RefreshCw, Search } from "lucide-react"
import { useEffect, useMemo, useState } from "react"

import { Input } from "@/components/ui/input"
import { isActive, Pill, ScanStatusBadge } from "@/components/livegang/shared"
import { apiFetch, formatDateTime, type LaunchCustomer } from "@/lib/launch-checklist"

function OutdatedPill() {
  return (
    <span title="Gebaseerd op een oudere nulmeting — scan opnieuw.">
      <Pill tone="amber">
        <RefreshCw className="size-3" /> Verouderd
      </Pill>
    </span>
  )
}

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
            const geoScan = customer.latest_geo_scan
            const progress = customer.checklist_progress
            const contentScan = customer.latest_content_scan
            const contentProgress = customer.content_progress
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
                  <div className="flex flex-wrap items-center justify-end gap-2">
                    {contentScan && isActive(contentScan.status) ? (
                      <>
                        <Pill tone="blue">Fase 3</Pill>
                        <ScanStatusBadge status={contentScan.status} />
                      </>
                    ) : contentProgress ? (
                      <>
                        <Pill tone="blue">Fase 3</Pill>
                        <Pill tone={contentProgress.percent >= 80 ? "green" : contentProgress.percent >= 50 ? "amber" : "red"}>
                          {contentProgress.percent}% checklist
                        </Pill>
                        {customer.content_outdated && <OutdatedPill />}
                      </>
                    ) : geoScan && isActive(geoScan.status) ? (
                      <>
                        <Pill tone="blue">Fase 2</Pill>
                        <ScanStatusBadge status={geoScan.status} />
                      </>
                    ) : progress ? (
                      <>
                        <Pill tone="blue">Fase 2</Pill>
                        <Pill tone={progress.percent >= 80 ? "green" : progress.percent >= 50 ? "amber" : "red"}>
                          {progress.percent}% checklist
                        </Pill>
                        {customer.geo_outdated && <OutdatedPill />}
                      </>
                    ) : (
                      <>
                        <Pill tone="blue">Fase 1</Pill>
                        {scan ? <ScanStatusBadge status={scan.status} /> : <Pill>Niet gestart</Pill>}
                        {issues && issues.total > 0 && (
                          <Pill tone={(issues.by_severity.hoog ?? 0) > 0 ? "red" : "amber"}>
                            {issues.total} actiepunten
                          </Pill>
                        )}
                      </>
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
