"use client"

import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type LabelProps,
} from "recharts"

import { ChartTooltip } from "./ChartTooltip"
import { AXIS_TICK, AXIS_TICK_COUNT, CHART, niceAxisMax } from "./theme"
import type { ChartDatum, ChartMarker, ChartSeries, TickFormatter, ValueFormatter } from "./types"

export type TrendLineChartProps = {
  data: ChartDatum[]
  /** Reeksen met dezelfde eenheid (één y-as; nooit twee schalen). */
  series: ChartSeries[]
  formatValue: ValueFormatter
  formatTick?: TickFormatter
  /** Vaste y-as, bijv. [0, 100]. Standaard vanaf 0 (of automatisch bij `invertY`). */
  yDomain?: [number, number]
  /** Y-as omgekeerd (lager is beter, bijv. positie). */
  invertY?: boolean
  /** Alleen hele getallen op de y-as (aantallen). */
  integerTicks?: boolean
  markers?: ChartMarker[]
  /** Toegankelijke omschrijving van de grafiek. */
  description?: string
}

/**
 * Verloop over de metingen: 2px-lijnen met punten (r=4, ring in de kaartkleur),
 * gaten bij niet-gemeten waarden (`null`), kruisdraad + tooltip met alle reeksen.
 * Bij één reeks staat de laatste waarde direct aan het eind van de lijn.
 */
export default function TrendLineChart({
  data,
  series,
  formatValue,
  formatTick,
  yDomain,
  invertY = false,
  integerTicks = false,
  markers = [],
  description,
}: TrendLineChartProps) {
  const labels = new Map(data.map((d) => [d.x, d.xLabel]))
  const domain: [number | "auto", number | "auto" | ((max: number) => number)] = yDomain
    ? yDomain
    : invertY
      ? ["auto", "auto"]
      : [0, (max: number) => niceAxisMax(max)]

  const single = series.length === 1 ? series[0] : null
  const lastIndex = single ? findLastIndex(data, (d) => typeof d[single.key] === "number") : -1

  return (
    <ResponsiveContainer width="100%" height="100%" minWidth={0}>
      <LineChart data={data} margin={{ top: 16, right: single ? 56 : 16, bottom: 0, left: 0 }} desc={description}>
        <CartesianGrid vertical={false} stroke={CHART.grid} />
        <XAxis
          dataKey="x"
          tickFormatter={(x: string) => labels.get(x) ?? x}
          tick={AXIS_TICK}
          tickLine={false}
          axisLine={{ stroke: CHART.axis }}
          interval="preserveStartEnd"
          minTickGap={12}
          padding={{ left: 16, right: 16 }}
        />
        <YAxis
          tick={AXIS_TICK}
          tickLine={false}
          axisLine={false}
          width={56}
          domain={domain}
          tickCount={AXIS_TICK_COUNT}
          reversed={invertY}
          allowDecimals={!integerTicks}
          tickFormatter={formatTick}
        />
        <Tooltip
          cursor={{ stroke: CHART.reference, strokeWidth: 1 }}
          filterNull={false}
          isAnimationActive={false}
          content={(props) => <ChartTooltip {...props} formatValue={formatValue} keyShape="line" />}
        />
        {markers.map((m) => (
          <ReferenceLine
            key={m.x}
            x={m.x}
            stroke={CHART.reference}
            strokeWidth={1}
            label={{ value: m.label, position: "insideTopLeft", fill: CHART.text, fontSize: CHART.fontSize }}
          />
        ))}
        {series.map((s) => (
          <Line
            key={s.key}
            type="linear"
            dataKey={s.key}
            name={s.label}
            stroke={s.color}
            strokeWidth={CHART.lineWidth}
            strokeLinecap="round"
            strokeLinejoin="round"
            connectNulls={false}
            dot={{ r: CHART.dotRadius, fill: s.color, stroke: CHART.surface, strokeWidth: 2 }}
            activeDot={{ r: CHART.dotRadius + 1, fill: s.color, stroke: CHART.surface, strokeWidth: 2 }}
            isAnimationActive={false}
            label={single ? (props: LabelProps) => endLabel(props, lastIndex, (v) => formatValue(v, s.key)) : false}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  )
}

/** Directe waarde aan het eind van de lijn (alleen het laatste gemeten punt). */
function endLabel(props: LabelProps, lastIndex: number, format: (value: number) => string) {
  const value = Number(props.value)
  if (props.index !== lastIndex || !Number.isFinite(value)) return <g />
  return (
    <text x={Number(props.x ?? 0) + 8} y={Number(props.y ?? 0)} dy={4} fill={CHART.ink} fontSize={CHART.fontSize} fontWeight={600}>
      {format(value)}
    </text>
  )
}

function findLastIndex<T>(items: T[], predicate: (item: T) => boolean): number {
  for (let i = items.length - 1; i >= 0; i--) if (predicate(items[i])) return i
  return -1
}
