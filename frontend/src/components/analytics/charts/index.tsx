"use client"

/**
 * Ingang van de grafieklaag. De Recharts-grafieken laden alleen in de browser
 * (`ssr: false`): ze meten hun container, en op de server is die breedte 0.
 * Recharts komt zo ook alleen in de bundel van de analytics-pagina's.
 * Alleen deze map importeert `recharts`.
 */
import dynamic from "next/dynamic"

import { ChartPlaceholder } from "./ChartFrame"

export const TrendLineChart = dynamic(() => import("./TrendLineChart"), { ssr: false, loading: ChartPlaceholder })
export const StackedBarChart = dynamic(() => import("./StackedBarChart"), { ssr: false, loading: ChartPlaceholder })
export const RankBarChart = dynamic(() => import("./RankBarChart"), { ssr: false, loading: ChartPlaceholder })

export { ChartFrame, ChartLegend, ChartPlaceholder } from "./ChartFrame"
export type { RankBarItem, RankBarChartProps } from "./RankBarChart"
export type { TrendLineChartProps } from "./TrendLineChart"
export type { StackedBarChartProps } from "./StackedBarChart"
export {
  SERIES_COLORS,
  STATUS_COLORS,
  MAX_SERIES,
  RANK_ROW_HEIGHT,
  rankBarChartHeight,
  seriesColor,
  type StatusTone,
} from "./theme"
export type { ChartDatum, ChartMarker, ChartSeries, TickFormatter, ValueFormatter } from "./types"
