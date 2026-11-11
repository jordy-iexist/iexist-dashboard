"use client"

import { useCallback, useEffect, useState } from "react"

import { CwvBadge } from "@/components/livegang/shared"
import { apiFetch, type CwvRating, type LaunchScanPage } from "@/lib/launch-checklist"
import { usePolling } from "@/hooks/use-polling"
import { cn } from "@/lib/utils"

const THRESHOLDS: Record<string, [number, number]> = {
  lcp: [2500, 4000],
  cls: [0.1, 0.25],
  tbt: [200, 600],
  fcp: [1800, 3000],
  inp: [200, 500],
}

function rate(metric: string, value: number | null | undefined): CwvRating | null {
  if (value === null || value === undefined) return null
  const [good, poor] = THRESHOLDS[metric]
  return value <= good ? "good" : value > poor ? "poor" : "needs_improvement"
}

function Cell({ metric, value, format }: { metric: string; value: number | null | undefined; format: (v: number) => string }) {
  const rating = rate(metric, value)
  return (
    <td
      className={cn(
        "px-3 py-2 text-xs font-medium tabular-nums",
        rating === "good" && "text-green-700 dark:text-green-400",
        rating === "needs_improvement" && "text-amber-700 dark:text-amber-400",
        rating === "poor" && "text-red-700 dark:text-red-400"
      )}
    >
      {value === null || value === undefined ? "—" : format(value)}
    </td>
  )
}

const seconds = (v: number) => `${(v / 1000).toFixed(1)} s`
const ms = (v: number) => `${Math.round(v)} ms`

export function VitalsTab({ scanId, measuring }: { scanId: string; measuring: boolean }) {
  const [pages, setPages] = useState<LaunchScanPage[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  const fetchPages = useCallback(
    () => apiFetch<{ pages: LaunchScanPage[] }>(`/scans/${scanId}/pages?filter=cwv_measured&limit=500`),
    [scanId]
  )

  useEffect(() => {
    let cancelled = false
    fetchPages()
      .then((r) => !cancelled && setPages(r.pages))
      .catch((err: Error) => !cancelled && setError(err.message))
    return () => {
      cancelled = true
    }
  }, [fetchPages])

  // Tijdens het meten elke 5 s verversen.
  usePolling(async () => setPages((await fetchPages()).pages), measuring, 5000)

  if (error) return <p className="text-sm text-red-600">{error}</p>
  if (!pages) return <p className="text-sm text-muted-foreground">Laden…</p>

  const sorted = [...pages].sort(
    (a, b) => (a.cwv?.lab?.performance_score ?? 101) - (b.cwv?.lab?.performance_score ?? 101)
  )

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        Gemeten met Google PageSpeed Insights (mobiel). Velddata (echte Chrome-gebruikers, CrUX) is leidend als
        die voor de pagina beschikbaar is, anders labdata (Lighthouse). INP bestaat alleen als velddata; in het lab is
        TBT de vervanger.
      </p>
      {sorted.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {measuring ? "Metingen lopen…" : "Er zijn geen Core Web Vitals gemeten."}
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full min-w-[860px] text-sm">
            <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">Pagina</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Score</th>
                <th className="px-3 py-2 font-medium">LCP</th>
                <th className="px-3 py-2 font-medium">CLS</th>
                <th className="px-3 py-2 font-medium">TBT</th>
                <th className="px-3 py-2 font-medium">FCP</th>
                <th className="px-3 py-2 font-medium">Veld LCP</th>
                <th className="px-3 py-2 font-medium">Veld INP</th>
                <th className="px-3 py-2 font-medium">Veld CLS</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {sorted.map((page) => {
                const lab = page.cwv?.lab
                const field = page.cwv?.field && !page.cwv.field.origin_fallback ? page.cwv.field : null
                return (
                  <tr key={page.id}>
                    <td className="max-w-[260px] px-3 py-2">
                      <a href={page.url} target="_blank" rel="noreferrer noopener" className="block truncate hover:underline" title={page.url}>
                        {page.path}
                      </a>
                      {page.cwv?.error && <p className="truncate text-xs text-red-600">{page.cwv.error}</p>}
                    </td>
                    <td className="px-3 py-2">
                      <CwvBadge rating={page.cwv_status} />
                      {page.cwv?.source && <span className="ml-1 text-[10px] text-muted-foreground">{page.cwv.source === "field" ? "veld" : "lab"}</span>}
                    </td>
                    <td className="px-3 py-2 text-xs font-semibold tabular-nums">{lab?.performance_score ?? "—"}</td>
                    <Cell metric="lcp" value={lab?.lcp} format={seconds} />
                    <Cell metric="cls" value={lab?.cls} format={(v) => v.toFixed(2)} />
                    <Cell metric="tbt" value={lab?.tbt} format={ms} />
                    <Cell metric="fcp" value={lab?.fcp} format={seconds} />
                    <Cell metric="lcp" value={field?.lcp?.value} format={seconds} />
                    <Cell metric="inp" value={field?.inp?.value} format={ms} />
                    <Cell metric="cls" value={field?.cls?.value} format={(v) => v.toFixed(2)} />
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
