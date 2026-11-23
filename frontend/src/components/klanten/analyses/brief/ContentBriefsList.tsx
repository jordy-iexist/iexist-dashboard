"use client"

import { useCallback, useState } from "react"
import Link from "next/link"
import { Loader2, Swords } from "lucide-react"

import { formatInt } from "@/components/klanten/analyses/result-parts"
import { Pill, PollingFailedNotice, type Tone } from "@/components/livegang/shared"
import { Button } from "@/components/ui/button"
import { usePolling } from "@/hooks/use-polling"
import { analysesHref, formatAnalysisDate } from "@/lib/competitor-analysis"
import {
  BRIEF_STATUS_LABELS,
  briefHref,
  fetchBriefs,
  isBriefActive,
  type ContentBriefListItem,
  type ContentBriefStatus,
} from "@/lib/content-brief"
import { cn } from "@/lib/utils"

const POLL_INTERVAL_MS = 5000

const COLUMNS: { label: string; width?: number; srOnly?: boolean }[] = [
  { label: "Zoekwoord", width: 220 },
  { label: "Title" },
  { label: "Woorden", width: 88 },
  { label: "Status", width: 190 },
  { label: "Bijgewerkt", width: 168 },
  { label: "Openen", width: 96, srOnly: true },
]

const STATUS_TONES: Record<ContentBriefStatus, Tone> = {
  pending: "blue",
  brief: "blue",
  concept: "blue",
  completed: "green",
  failed: "red",
}

const td = "px-2 py-3 align-middle"

function AnalysesButton({ customerId }: { customerId: string }) {
  return (
    <Button asChild className="font-semibold">
      <Link href={analysesHref(customerId)}>
        <Swords />
        Naar de concurrentieanalyses
      </Link>
    </Button>
  )
}

/** Content briefs van één klant; ververst zichzelf zolang er een brief wordt gemaakt. */
export function ContentBriefsList({
  customerId,
  initialItems,
  initialFailed,
  limit,
}: {
  customerId: string
  initialItems: ContentBriefListItem[]
  /** Ophalen op de server mislukt: fouttoestand met "Opnieuw proberen". */
  initialFailed: boolean
  limit: number
}) {
  const [items, setItems] = useState(initialItems)
  const [failed, setFailed] = useState(initialFailed)
  const [retrying, setRetrying] = useState(false)

  const load = useCallback(async () => {
    const response = await fetchBriefs(customerId, limit)
    setItems(response.items)
    setFailed(false)
  }, [customerId, limit])

  const polling = !failed && items.some((item) => isBriefActive(item.status))
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
          De content briefs konden niet worden opgehaald. Probeer het later opnieuw.
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
          <p className="text-base font-semibold">Nog geen content briefs</p>
          <p className="text-sm text-muted-foreground">
            Een content brief maak je vanuit een concurrentieanalyse: open het resultaat van een
            zoekwoord en kies “Content brief maken”. Claude stelt dan de brief op en schrijft een
            concepttekst om te reviewen.
          </p>
        </div>
        <AnalysesButton customerId={customerId} />
      </div>
    )
  }

  return (
    <section aria-label="Content briefs" className="flex flex-col gap-4 rounded-xl border bg-card px-6 py-5">
      <PollingFailedNotice failing={failing} />
      <div className="overflow-x-auto">
        <table className="w-full min-w-[860px] table-fixed text-[13px]">
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
              const href = briefHref(customerId, item.analysis_id, item.keyword_id)
              const active = isBriefActive(item.status)
              return (
                <tr key={item.id} className="border-b">
                  <td className={cn(td, "max-w-0")}>
                    <Link
                      href={href}
                      title={item.keyword}
                      className="block truncate font-medium underline-offset-2 hover:underline"
                    >
                      {item.keyword}
                    </Link>
                  </td>
                  <td className={cn(td, "max-w-0")}>
                    <span
                      title={item.title ?? item.error_message ?? undefined}
                      className="block truncate text-muted-foreground"
                    >
                      {item.title ?? "—"}
                    </span>
                  </td>
                  <td className={cn(td, "tabular-nums")}>{formatInt(item.word_count)}</td>
                  <td className={td}>
                    <Pill tone={STATUS_TONES[item.status] ?? "muted"}>
                      {active && <Loader2 className="size-3 animate-spin" aria-hidden="true" />}
                      {BRIEF_STATUS_LABELS[item.status] ?? item.status}
                    </Pill>
                  </td>
                  <td className={cn(td, "whitespace-nowrap tabular-nums text-muted-foreground")}>
                    {formatAnalysisDate(item.updated_at) ?? "—"}
                  </td>
                  <td className={cn(td, "text-right")}>
                    <Link
                      href={href}
                      className="font-semibold whitespace-nowrap text-primary underline-offset-2 hover:underline"
                    >
                      {active ? "Volgen →" : "Bekijk →"}
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
