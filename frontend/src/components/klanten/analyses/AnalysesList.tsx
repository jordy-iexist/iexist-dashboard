"use client"

import { useCallback, useState } from "react"
import Link from "next/link"
import { Plus } from "lucide-react"

import { AnalysisStatusPill } from "@/components/klanten/analyses/AnalysisStatusPill"
import { PollingFailedNotice } from "@/components/livegang/shared"
import { Button } from "@/components/ui/button"
import { usePolling } from "@/hooks/use-polling"
import {
  analysisHref,
  fetchAnalyses,
  formatAnalysisDate,
  formatKeywords,
  isActive,
  newAnalysisHref,
  type AnalysisListItem,
} from "@/lib/competitor-analysis"
import { cn } from "@/lib/utils"

const POLL_INTERVAL_MS = 5000

const COLUMNS: { label: string; width?: number; srOnly?: boolean }[] = [
  { label: "Datum", width: 168 },
  { label: "Zoekwoorden" },
  { label: "Top", width: 72 },
  { label: "Status", width: 180 },
  { label: "Resultaat", width: 112, srOnly: true },
]

const td = "px-2 py-3 align-middle"

function NewAnalysisButton({ customerId }: { customerId: string }) {
  return (
    <Button asChild className="font-semibold">
      <Link href={newAnalysisHref(customerId)}>
        <Plus />
        Nieuwe analyse
      </Link>
    </Button>
  )
}

/** Analyses van één klant; ververst zichzelf zolang er een analyse loopt. */
export function AnalysesList({
  customerId,
  initialItems,
  initialFailed,
  limit,
}: {
  customerId: string
  initialItems: AnalysisListItem[]
  /** Ophalen op de server mislukt: fouttoestand met "Opnieuw proberen". */
  initialFailed: boolean
  limit: number
}) {
  const [items, setItems] = useState(initialItems)
  const [failed, setFailed] = useState(initialFailed)
  const [retrying, setRetrying] = useState(false)

  const load = useCallback(async () => {
    const response = await fetchAnalyses(customerId, limit)
    setItems(response.items)
    setFailed(false)
  }, [customerId, limit])

  const polling = !failed && items.some((item) => isActive(item.status))
  const { failing } = usePolling(load, polling, POLL_INTERVAL_MS)

  async function retry() {
    setRetrying(true)
    try {
      await load()
    } catch {
      setFailed(true)
    } finally {
      setRetrying(false)
    }
  }

  if (failed) {
    return (
      <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed bg-card px-6 py-10 text-center">
        <p className="text-sm text-muted-foreground">
          De analyses konden niet worden opgehaald. Probeer het later opnieuw.
        </p>
        <Button variant="outline" onClick={retry} disabled={retrying}>
          {retrying ? "Bezig met laden…" : "Opnieuw proberen"}
        </Button>
      </div>
    )
  }

  if (items.length === 0) {
    return (
      <div className="flex flex-col items-center gap-4 rounded-xl border border-dashed bg-card px-6 py-10 text-center">
        <div className="max-w-xl space-y-1">
          <p className="text-base font-semibold">Nog geen analyses</p>
          <p className="text-sm text-muted-foreground">
            Een concurrentieanalyse haalt per zoekwoord de top van Google op, leest die pagina&apos;s
            en de eigen pagina uit en zet ze naast elkaar: inhoud, structuur, autoriteit en techniek,
            met concrete verbeterpunten.
          </p>
        </div>
        <NewAnalysisButton customerId={customerId} />
      </div>
    )
  }

  return (
    <section aria-label="Analyses" className="flex flex-col gap-4 rounded-xl border bg-card px-6 py-5">
      <PollingFailedNotice failing={failing} />
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] table-fixed text-[13px]">
          <colgroup>
            {COLUMNS.map((column) => (
              <col key={column.label} style={column.width ? { width: column.width } : undefined} />
            ))}
          </colgroup>
          <thead>
            <tr>
              {COLUMNS.map((column) => (
                <th
                  key={column.label}
                  scope="col"
                  className="bg-muted p-2 text-left text-xs font-semibold text-muted-foreground first:rounded-l-md last:rounded-r-md"
                >
                  {column.srOnly ? <span className="sr-only">{column.label}</span> : column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {items.map((item) => {
              const href = analysisHref(customerId, item.id)
              return (
                <tr key={item.id} className="border-b">
                  <td className={cn(td, "whitespace-nowrap tabular-nums text-muted-foreground")}>
                    {formatAnalysisDate(item.created_at) ?? "—"}
                  </td>
                  <td className={cn(td, "max-w-0")}>
                    <Link
                      href={href}
                      title={item.keywords.join(", ")}
                      className="block truncate font-medium underline-offset-2 hover:underline"
                    >
                      {formatKeywords(item.keywords, item.total_keywords)}
                    </Link>
                  </td>
                  <td className={cn(td, "tabular-nums")}>Top {item.top_n}</td>
                  <td className={td}>
                    <AnalysisStatusPill status={item.status} />
                  </td>
                  <td className={cn(td, "text-right")}>
                    <Link
                      href={href}
                      className="font-semibold whitespace-nowrap text-primary underline-offset-2 hover:underline"
                    >
                      {isActive(item.status) ? "Volgen →" : "Bekijk →"}
                    </Link>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </section>
  )
}
