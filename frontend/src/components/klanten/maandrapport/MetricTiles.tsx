"use client"

import { useState } from "react"
import { Loader2, Pencil } from "lucide-react"

import { formatInt } from "@/components/klanten/analyses/result-parts"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import {
  LEADS_MAX,
  METRIC_ORDER,
  NOT_LINKED_METRIC_STATES,
  USABLE_METRIC_STATES,
  saveManual,
  type Leads,
  type Metric,
  type MetricKey,
  type Metrics,
  type MonthlyReport,
} from "@/lib/monthly-report"
import { cn } from "@/lib/utils"

const LABELS: Record<MetricKey, string> = {
  clicks: "Bezoekers uit Google",
  top10: "Zoekwoorden in top 10",
  leads: "Aanvragen via Google",
  ai_mentions: "Genoemd door AI",
}

type Delta = { amount: number; text: string }

/** "+12%" of "+3" (met echt minteken); 0 zonder teken. */
function signed(amount: number, suffix = "") {
  const text = `${formatInt(Math.abs(amount))}${suffix}`
  return amount > 0 ? `+${text}` : amount < 0 ? `−${text}` : text
}

function deltaText(amount: number, suffix: string, against: string): Delta {
  return { amount, text: amount === 0 ? `gelijk aan ${against}` : `${signed(amount, suffix)} t.o.v. ${against}` }
}

/** Toestand zonder getal als korte tekst; null bij een bruikbaar cijfer. */
function stateText(metric: Metric) {
  if (USABLE_METRIC_STATES.includes(metric.state)) return null
  return NOT_LINKED_METRIC_STATES.includes(metric.state) ? "niet gekoppeld" : "niet beschikbaar"
}

function Tile({
  label,
  value,
  sub,
  subTitle,
  delta,
  action,
}: {
  label: string
  value: string
  sub?: string | null
  subTitle?: string
  delta?: Delta | null
  action?: React.ReactNode
}) {
  return (
    <div className="flex min-w-0 flex-col gap-1 rounded-lg bg-muted px-3.5 py-3">
      <div className="flex items-start justify-between gap-1">
        <p className="text-[11px] leading-4 text-muted-foreground">{label}</p>
        {action}
      </div>
      <p className="text-xl leading-7 font-bold tabular-nums">{value}</p>
      {sub && (
        <p className="text-[11px] leading-4 text-muted-foreground" title={subTitle}>
          {sub}
        </p>
      )}
      {delta && (
        <p
          className={cn(
            "text-[11px] leading-4 font-semibold",
            delta.amount > 0 && "text-status-good",
            delta.amount < 0 && "text-status-critical",
            delta.amount === 0 && "text-muted-foreground"
          )}
        >
          {delta.text}
        </p>
      )}
    </div>
  )
}

function AutoTile({
  metricKey,
  metric,
  previousMonthName,
}: {
  metricKey: Exclude<MetricKey, "leads">
  metric: Metric | null
  previousMonthName: string
}) {
  const label = LABELS[metricKey]
  // Nog geen cijfers (geen rapport, of de eerste run loopt nog).
  if (!metric) return <Tile label={label} value="–" />

  const unavailable = stateText(metric)
  if (unavailable || metric.value == null) {
    return <Tile label={label} value="–" sub={unavailable ?? "niet beschikbaar"} subTitle={metric.message ?? undefined} />
  }

  const value = metric.value
  const diff = metric.delta ?? (metric.previous != null ? value - metric.previous : null)

  if (metricKey === "clicks") {
    const delta =
      metric.delta_pct != null
        ? deltaText(Math.round(metric.delta_pct), "%", previousMonthName)
        : diff != null
          ? deltaText(diff, "", previousMonthName)
          : null
    return <Tile label={label} value={formatInt(value)} delta={delta} />
  }

  if (metricKey === "top10") {
    return (
      <Tile
        label={label}
        value={formatInt(value)}
        sub={metric.total != null ? `van ${formatInt(metric.total)} gevolgde zoekwoorden` : null}
        delta={diff != null ? deltaText(diff, "", "een maand geleden") : null}
      />
    )
  }

  return (
    <Tile
      label={label}
      value={metric.total != null ? `${formatInt(value)} / ${formatInt(metric.total)}` : formatInt(value)}
      sub={metric.total != null ? "prompts met een vermelding" : null}
      delta={metric.previous != null && diff != null ? deltaText(diff, "", previousMonthName) : null}
    />
  )
}

/** Leeg = null; anders een heel getal van 0 t/m `LEADS_MAX`, of `undefined` als het ongeldig is. */
function parseLeads(raw: string): number | null | undefined {
  const text = raw.trim()
  if (!text) return null
  if (!/^\d+$/.test(text)) return undefined
  const value = Number(text)
  return value <= LEADS_MAX ? value : undefined
}

function LeadsEditor({
  customerId,
  month,
  leads,
  previousMonthName,
  onSaved,
}: {
  customerId: string
  month: string
  leads: Leads
  previousMonthName: string
  onSaved: (report: MonthlyReport) => void
}) {
  const [open, setOpen] = useState(false)
  const [current, setCurrent] = useState("")
  const [previous, setPrevious] = useState("")
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function changeOpen(next: boolean) {
    if (next) {
      // Bij openen de opgeslagen cijfers invullen; een standaardwaarde uit het vorige rapport
      // staat als placeholder, zodat leeg laten die waarde houdt.
      setCurrent(leads.value != null ? String(leads.value) : "")
      setPrevious(leads.previous_source === "manual" && leads.previous != null ? String(leads.previous) : "")
      setError(null)
    }
    setOpen(next)
  }

  async function save(event: React.FormEvent) {
    event.preventDefault()
    const value = parseLeads(current)
    const previousValue = parseLeads(previous)
    if (value === undefined || previousValue === undefined) {
      setError(`Vul een heel getal van 0 tot en met ${formatInt(LEADS_MAX)} in, of laat het veld leeg.`)
      return
    }
    setSaving(true)
    setError(null)
    try {
      onSaved(await saveManual(customerId, month, { leads: value, leads_previous: previousValue }))
      setOpen(false)
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : "Opslaan is mislukt.")
    } finally {
      setSaving(false)
    }
  }

  const previousPlaceholder =
    leads.previous_source === "previous_report" && leads.previous != null
      ? `${formatInt(leads.previous)} (uit rapport ${previousMonthName})`
      : "Niet ingevuld"

  return (
    <Popover open={open} onOpenChange={changeOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Aanvragen invullen"
          title="Aanvragen invullen"
          className="-mt-1.5 -mr-1.5 size-6 text-muted-foreground"
        >
          <Pencil className="size-3.5" aria-hidden="true" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-72 p-4">
        <form onSubmit={save} className="space-y-3" noValidate>
          <div className="space-y-0.5">
            <p className="text-sm font-semibold">Aanvragen via Google</p>
            <p className="text-xs text-muted-foreground">GA4 is niet gekoppeld; vul het aantal met de hand in.</p>
          </div>
          <label className="block space-y-1">
            <span className="text-xs font-medium">Deze maand</span>
            <Input
              type="number"
              inputMode="numeric"
              min={0}
              max={LEADS_MAX}
              step={1}
              value={current}
              onChange={(event) => setCurrent(event.target.value)}
              placeholder="Niet ingevuld"
              autoFocus
            />
          </label>
          <label className="block space-y-1">
            <span className="text-xs font-medium">Vorige maand</span>
            <Input
              type="number"
              inputMode="numeric"
              min={0}
              max={LEADS_MAX}
              step={1}
              value={previous}
              onChange={(event) => setPrevious(event.target.value)}
              placeholder={previousPlaceholder}
            />
          </label>
          {error && (
            <p role="alert" className="text-xs text-status-critical">
              {error}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" size="sm" onClick={() => setOpen(false)} disabled={saving}>
              Annuleren
            </Button>
            <Button type="submit" size="sm" disabled={saving}>
              {saving && <Loader2 className="animate-spin" aria-hidden="true" />}
              Opslaan
            </Button>
          </div>
        </form>
      </PopoverContent>
    </Popover>
  )
}

/**
 * De vier cijfertegels op het rapportvel, in de volgorde van `METRIC_ORDER`. De tegel Aanvragen
 * komt uit `leads` van het antwoord (handmatig), niet uit de momentopname; invullen kan altijd.
 */
export function MetricTiles({
  customerId,
  month,
  metrics,
  leads,
  previousMonthName,
  onLeadsSaved,
}: {
  customerId: string
  month: string
  /** null = nog geen cijfers opgehaald. */
  metrics: Metrics | null
  leads: Leads
  previousMonthName: string
  onLeadsSaved: (report: MonthlyReport) => void
}) {
  return (
    <div className="grid grid-cols-2 gap-3 @xl:grid-cols-4">
      {METRIC_ORDER.map((key) => {
        if (key !== "leads") {
          return (
            <AutoTile key={key} metricKey={key} metric={metrics?.[key] ?? null} previousMonthName={previousMonthName} />
          )
        }
        const filled = leads.value != null
        return (
          <Tile
            key={key}
            label={LABELS.leads}
            value={filled ? formatInt(leads.value) : "–"}
            sub={filled ? "GA4 niet gekoppeld · handmatig ingevuld" : "GA4 niet gekoppeld · nog niet ingevuld"}
            delta={
              leads.value != null && leads.previous != null
                ? deltaText(leads.value - leads.previous, "", previousMonthName)
                : null
            }
            action={
              <LeadsEditor
                customerId={customerId}
                month={month}
                leads={leads}
                previousMonthName={previousMonthName}
                onSaved={onLeadsSaved}
              />
            }
          />
        )
      })}
    </div>
  )
}
