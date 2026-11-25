// Notaties voor het scherm Search Console-inzichten.

import { formatDecimal } from "@/components/klanten/dashboard/trend"

/** CTR (fractie 0–1) als percentage met één decimaal: 0.0213 → "2,1%"; null = "—". */
export function formatCtr(value: number | null | undefined) {
  return value == null ? "—" : `${formatDecimal(value * 100, 1)}%`
}

/** Positie met één decimaal: 11.24 → "11,2"; null = "—". */
export function formatPosition(value: number | null | undefined) {
  return value == null ? "—" : formatDecimal(value, 1)
}

/** Pad met query van een URL, zonder #fragment; bij een ongeldige URL de tekst zelf. */
export function urlPath(url: string) {
  try {
    const parsed = new URL(url)
    return `${parsed.pathname}${parsed.search}`
  } catch {
    return url
  }
}
