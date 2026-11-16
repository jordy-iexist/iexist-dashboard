"use client"

import { Bar, BarChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"

import { ChartTooltip } from "./ChartTooltip"
import { AXIS_TICK, AXIS_TICK_COUNT, CHART, niceAxisMax } from "./theme"
import type { ChartDatum, ChartMarker, ChartSeries, TickFormatter, ValueFormatter } from "./types"

export type StackedBarChartProps = {
  data: ChartDatum[]
  /** Reeksen in stapelvolgorde (onderste eerst). Zelfde eenheid. */
  series: ChartSeries[]
  formatValue: ValueFormatter
  formatTick?: TickFormatter
  /** `false`: staven naast elkaar per meting i.p.v. gestapeld. */
  stacked?: boolean
  yDomain?: [number, number]
  integerTicks?: boolean
  /** Verticale markering aan het begin van de staaf met `x` (bijv. regelset-wissel). */
  markers?: ChartMarker[]
  description?: string
}

/**
 * Kolommen per meting, gestapeld of gegroepeerd. Max. 24px breed, 4px afgerond
 * aan de data-kant en recht op de basislijn; 2px gat in de kaartkleur tussen
 * segmenten en staven. Tooltip per meting met alle reeksen.
 */
export default function StackedBarChart({
  data,
  series,
  formatValue,
  formatTick,
  stacked = true,
  yDomain,
  integerTicks = false,
  markers = [],
  description,
}: StackedBarChartProps) {
  const labels = new Map(data.map((d) => [d.x, d.xLabel]))
  const r = CHART.barRadius

  return (
    <ResponsiveContainer width="100%" height="100%" minWidth={0}>
      <BarChart
        data={data}
        margin={{ top: 16, right: 16, bottom: 0, left: 0 }}
        barGap={2}
        barCategoryGap="20%"
        desc={description}
      >
        <CartesianGrid vertical={false} stroke={CHART.grid} />
        <XAxis
          dataKey="x"
          tickFormatter={(x: string) => labels.get(x) ?? x}
          tick={AXIS_TICK}
          tickLine={false}
          axisLine={{ stroke: CHART.axis }}
          interval="preserveStartEnd"
          minTickGap={12}
        />
        <YAxis
          tick={AXIS_TICK}
          tickLine={false}
          axisLine={false}
          width={56}
          domain={yDomain ?? [0, (max: number) => niceAxisMax(max)]}
          tickCount={AXIS_TICK_COUNT}
          allowDecimals={!integerTicks}
          tickFormatter={formatTick}
        />
        <Tooltip
          cursor={{ fill: CHART.cursorFill, opacity: 0.6 }}
          filterNull={false}
          isAnimationActive={false}
          content={(props) => <ChartTooltip {...props} formatValue={formatValue} keyShape="rect" />}
        />
        {series.map((s, index) => {
          const isTop = !stacked || index === series.length - 1
          return (
            <Bar
              key={s.key}
              dataKey={s.key}
              name={s.label}
              stackId={stacked ? "stack" : undefined}
              fill={s.color}
              stroke={CHART.surface}
              strokeWidth={stacked ? 2 : 0}
              maxBarSize={CHART.maxBarSize}
              radius={isTop ? [r, r, 0, 0] : 0}
              isAnimationActive={false}
            />
          )
        })}
        {markers.map((m) => (
          <ReferenceLine
            key={m.x}
            x={m.x}
            position="start"
            stroke={CHART.reference}
            strokeWidth={1}
            ifOverflow="extendDomain"
            label={{ value: m.label, position: "insideTopLeft", fill: CHART.text, fontSize: CHART.fontSize }}
          />
        ))}
      </BarChart>
    </ResponsiveContainer>
  )
}
