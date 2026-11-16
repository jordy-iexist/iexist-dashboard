/** Gedeelde types van de grafieklaag; los van Recharts zodat aanroepers het niet hoeven te importeren. */

export type ChartSeries = {
  /** Data-key in `ChartDatum`. */
  key: string
  label: string
  /** CSS-kleur, bij voorkeur uit `theme.ts` (`seriesColor(i)` of `STATUS_COLORS`). */
  color: string
}

/** Eén punt op de x-as (een meting). `x` is uniek (scan-id), `xLabel` is wat de lezer ziet. */
export type ChartDatum = {
  x: string
  xLabel: string
  [seriesKey: string]: string | number | null
}

/** Verticale markering vóór het punt met `x` (bijv. een regelset-wissel). */
export type ChartMarker = { x: string; label: string }

/** Exacte waarde met eenheid, voor tooltips en directe labels. */
export type ValueFormatter = (value: number, seriesKey: string) => string

/** Korte notatie voor as-labels. */
export type TickFormatter = (value: number) => string
