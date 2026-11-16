"use client"

import { Bar, BarChart, CartesianGrid, Cell, LabelList, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"

import { ChartTooltip } from "./ChartTooltip"
import { AXIS_TICK, AXIS_TICK_COUNT, CHART, niceAxisMax, seriesColor } from "./theme"
import type { TickFormatter } from "./types"

export type RankBarItem = {
  /** Unieke sleutel (bijv. metric-key of klant-id). */
  key: string
  label: string
  /** `null` = niet gemeten: de rij blijft staan, zonder staaf. */
  value: number | null
  /** Gedimd tonen (bijv. verouderde meting). */
  muted?: boolean
}

export type RankBarChartProps = {
  items: RankBarItem[]
  /** Exacte waarde met eenheid (tooltip en label aan de staafpunt). */
  formatValue: (value: number) => string
  formatTick?: TickFormatter
  /** Eén kleur voor alle staven (één reeks); standaard slot 1. */
  color?: string
  /** Sorteren op waarde; `none` houdt de volgorde van `items`. */
  sort?: "desc" | "asc" | "none"
  /** Optionele referentielijn, bijv. de mediaan. Het label staat erboven: reken 16px extra hoogte. */
  reference?: { value: number; label: string }
  /** Vaste x-as, bijv. [0, 100]. */
  domain?: [number, number]
  /** Breedte van de labelkolom in px (lange namen lopen over meerdere regels). */
  labelWidth?: number
  /** Naam van de reeks in de tooltip (bijv. de metric). */
  seriesLabel?: string
  description?: string
}

/**
 * Horizontale, gesorteerde staven (één reeks, één kleur) met de waarde aan de
 * punt en een optionele referentielijn. Voor vergelijken tussen categorieën of klanten.
 */
export default function RankBarChart({
  items,
  formatValue,
  formatTick,
  color = seriesColor(0),
  sort = "desc",
  reference,
  domain,
  seriesLabel = "Waarde",
  labelWidth = 140,
  description,
}: RankBarChartProps) {
  const sorted =
    sort === "none"
      ? items
      : [...items].sort((a, b) => {
          if (a.value == null) return 1
          if (b.value == null) return -1
          return sort === "desc" ? b.value - a.value : a.value - b.value
        })
  const data = sorted.map((item) => ({ ...item, xLabel: item.label }))
  const r = CHART.barRadius

  return (
    <ResponsiveContainer width="100%" height="100%" minWidth={0}>
      <BarChart data={data} layout="vertical" margin={{ top: reference ? 20 : 4, right: 64, bottom: 0, left: 0 }} desc={description}>
        <CartesianGrid horizontal={false} stroke={CHART.grid} />
        <XAxis
          type="number"
          domain={domain ?? [0, (max: number) => niceAxisMax(max)]}
          tickCount={AXIS_TICK_COUNT}
          tick={AXIS_TICK}
          tickLine={false}
          axisLine={false}
          tickFormatter={formatTick}
        />
        <YAxis
          type="category"
          dataKey="label"
          tick={AXIS_TICK}
          tickLine={false}
          axisLine={{ stroke: CHART.axis }}
          width={labelWidth}
          interval={0}
        />
        <Tooltip
          cursor={{ fill: CHART.cursorFill, opacity: 0.6 }}
          filterNull={false}
          isAnimationActive={false}
          content={(props) => <ChartTooltip {...props} formatValue={(v) => formatValue(v)} keyShape="rect" />}
        />
        <Bar
          dataKey="value"
          name={seriesLabel}
          fill={color}
          maxBarSize={20}
          radius={[0, r, r, 0]}
          isAnimationActive={false}
        >
          {data.map((item) => (
            <Cell key={item.key} fillOpacity={item.muted ? 0.4 : 1} />
          ))}
          <LabelList
            dataKey="value"
            position="right"
            fill={CHART.ink}
            fontSize={CHART.fontSize}
            formatter={(value: unknown) => (typeof value === "number" ? formatValue(value) : "")}
          />
        </Bar>
        {reference && (
          <ReferenceLine
            x={reference.value}
            stroke={CHART.reference}
            strokeWidth={1}
            ifOverflow="extendDomain"
            label={{ value: reference.label, position: "top", fill: CHART.text, fontSize: CHART.fontSize }}
          />
        )}
      </BarChart>
    </ResponsiveContainer>
  )
}
