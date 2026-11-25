"use client"

import Link from "next/link"
import { ArrowLeftRight } from "lucide-react"
import { useId } from "react"

import type { TrendRequest } from "@/components/analytics/compare/CompareView"
import { MetricCompareTable } from "@/components/analytics/compare/MetricCompareTable"
import { useRequest } from "@/components/analytics/compare/use-request"
import { EmptyState, ErrorNote, InfoNotes, Notice } from "@/components/analytics/states"
import {
  AhrefsSection,
  AiSection,
  ComparisonSummary,
  IssuesSection,
  RankingsSection,
} from "@/components/livegang/comparison-parts"
import { Button } from "@/components/ui/button"
import { fetchCompare, type CompareResponse, type ScanRef, type TrendPoint } from "@/lib/analytics/api"
import { defaultScanPair, scanPairLabels } from "@/lib/analytics/compare"
import { formatDateTime } from "@/lib/launch-checklist"
import { cn } from "@/lib/utils"

const selectClass =
  "h-9 w-full min-w-0 rounded-md border border-input bg-card px-3 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 dark:bg-input/30"

const PHASE_NAMES: Record<number, string> = { 1: "Nulmeting", 4: "Kwartaalscan" }

export type ScanCompareProps = {
  trend: TrendRequest
  /** Keuze uit de URL; `null` of onbekend = standaard. */
  a: string | null
  b: string | null
  onPairChange: (a: string, b: string) => void
}

/** Modus Scan A/B: twee scans van de klant uit het adres naast elkaar. */
export function ScanCompare({ trend, a, b, onPairChange }: ScanCompareProps) {
  const { data, error, loading } = trend

  if (error) return <ErrorNote>{error}</ErrorNote>
  if (!data) return <p className="text-sm text-muted-foreground">Scans laden…</p>
  return (
    <ScanPicker customer={data.customer} points={data.points} a={a} b={b} onPairChange={onPairChange} dimmed={loading} />
  )
}

function ScanPicker({
  customer,
  points,
  a,
  b,
  onPairChange,
  dimmed,
}: {
  customer: { id: string; name: string }
  points: TrendPoint[]
  a: string | null
  b: string | null
  onPairChange: (a: string, b: string) => void
  dimmed: boolean
}) {
  const id = useId()
  const fallback = defaultScanPair(points)
  const known = (scanId: string | null) => !!scanId && points.some((p) => p.scan_id === scanId)
  const pairA = known(a) ? (a as string) : (fallback?.a ?? null)
  const pairB = known(b) ? (b as string) : (fallback?.b ?? null)
  const same = !!pairA && pairA === pairB
  const requestKey = pairA && pairB && !same ? `${pairA}|${pairB}` : null
  const compare = useRequest<CompareResponse>(requestKey, (signal) => fetchCompare(pairA ?? "", pairB ?? "", { signal }))

  if (!fallback || !pairA || !pairB) {
    return (
      <EmptyState>
        {points.length === 0
          ? `${customer.name} heeft nog geen voltooide nulmeting of kwartaalscan.`
          : `${customer.name} heeft nog maar één voltooide scan (nulmeting of kwartaalscan). Vergelijken kan vanaf de tweede scan.`}{" "}
        <Link
          href={`/dashboard/livegang/seo-geo/${encodeURIComponent(customer.id)}`}
          className="font-medium text-foreground underline underline-offset-4"
        >
          Naar de SEO/GEO-scan
        </Link>
      </EmptyState>
    )
  }

  const newestFirst = [...points].reverse()
  // Alleen een respons over de huidige klant tonen (de vorige blijft gedimd staan tijdens herladen).
  const ids = new Set(points.map((p) => p.scan_id))
  const result = compare.data && ids.has(compare.data.a.scan_id) && ids.has(compare.data.b.scan_id) ? compare.data : null

  return (
    <div className="space-y-6">
      <div className={cn("flex flex-wrap items-end gap-3 transition-opacity", dimmed && "opacity-60")}>
        <ScanSelect id={`${id}-a`} letter="A" value={pairA} points={newestFirst} onChange={(value) => onPairChange(value, pairB)} />
        <Button
          variant="outline"
          size="icon"
          className="hidden sm:inline-flex"
          onClick={() => onPairChange(pairB, pairA)}
          aria-label="A en B omwisselen"
          title="A en B omwisselen"
        >
          <ArrowLeftRight />
        </Button>
        <ScanSelect id={`${id}-b`} letter="B" value={pairB} points={newestFirst} onChange={(value) => onPairChange(pairA, value)} />
      </div>

      {same ? (
        <EmptyState>A en B zijn dezelfde scan. Kies twee verschillende scans om ze te vergelijken.</EmptyState>
      ) : compare.error ? (
        <ErrorNote>{compare.error}</ErrorNote>
      ) : !result ? (
        <p className="text-sm text-muted-foreground">Vergelijking laden…</p>
      ) : (
        <CompareResult result={result} requestedA={pairA} loading={compare.loading} onPairChange={onPairChange} />
      )}
    </div>
  )
}

function ScanSelect({
  id,
  letter,
  value,
  points,
  onChange,
}: {
  id: string
  letter: string
  value: string
  points: TrendPoint[]
  onChange: (scanId: string) => void
}) {
  return (
    <div className="w-full space-y-1 sm:w-80">
      <label htmlFor={id} className="text-xs font-medium text-muted-foreground">
        Scan {letter}
      </label>
      <select id={id} className={selectClass} value={value} onChange={(e) => onChange(e.target.value)}>
        {points.map((p) => (
          <option key={p.scan_id} value={p.scan_id}>
            {p.label} · {formatDateTime(p.date)}
          </option>
        ))}
      </select>
    </div>
  )
}

function CompareResult({
  result,
  requestedA,
  loading,
  onPairChange,
}: {
  result: CompareResponse
  requestedA: string
  loading: boolean
  onPairChange: (a: string, b: string) => void
}) {
  const labels = scanPairLabels(result.a, result.b)
  // Tijdens herladen hoort `result` nog bij de vorige keuze: dan niets over de volgorde zeggen.
  const swapped = !loading && result.a.scan_id !== requestedA

  return (
    <div className={cn("space-y-8 transition-opacity", loading && "opacity-60")} aria-busy={loading}>
      <div className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <ScanCard letter="A" scan={result.a} label={labels.before} />
          <ScanCard letter="B" scan={result.b} label={labels.after} />
        </div>
        {swapped && (
          <Notice>
            De vergelijking loopt altijd van oud naar nieuw. Je koos de nieuwere scan als A, dus staat{" "}
            {labels.before} hier als A en {labels.after} als B.{" "}
            <button
              type="button"
              className="font-medium text-foreground underline underline-offset-4"
              onClick={() => onPairChange(result.a.scan_id, result.b.scan_id)}
            >
              Keuze ook zo zetten
            </button>
          </Notice>
        )}
        <InfoNotes notes={result.notes} />
      </div>

      <section className="space-y-2">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Alle cijfers</h3>
        <MetricCompareTable metrics={result.metrics} labels={labels} caption={`Cijfers van ${labels.before} tegen ${labels.after}`} />
      </section>

      {(result.ai || result.issues || result.pages) && (
        <ComparisonSummary
          title="Samenvatting"
          ai={result.ai}
          issues={result.issues}
          pages={result.pages}
          labels={{ before: "A", after: "B" }}
        />
      )}
      {result.ai && <AiSection ai={result.ai} labels={labels} />}
      <RankingsSection
        rankings={result.rankings}
        labels={labels}
        emptyText="Geen posities: er zijn voor deze twee scans geen metingen uit de SEO-tracker, of voor deze klant worden geen zoekwoorden gevolgd."
      />
      <AhrefsSection ahrefs={result.ahrefs} labels={labels} />
      {result.issues && <IssuesSection issues={result.issues} labels={labels} />}
    </div>
  )
}

function ScanCard({ letter, scan, label }: { letter: string; scan: ScanRef; label: string }) {
  return (
    <div className="flex min-w-0 items-start gap-3 rounded-lg border bg-card p-3">
      <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-muted text-sm font-semibold">
        {letter}
      </span>
      <div className="min-w-0">
        <p className="truncate font-medium" title={label}>
          {label}
        </p>
        <p className="text-xs text-muted-foreground">
          {PHASE_NAMES[scan.phase] ?? `Fase ${scan.phase}`} · {formatDateTime(scan.date)}
        </p>
      </div>
    </div>
  )
}
