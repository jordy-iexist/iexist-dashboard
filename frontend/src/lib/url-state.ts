/**
 * Kleine helpers om weergavekeuzes (fase, tabblad) in de URL te bewaren, zodat
 * ze een refresh overleven en deelbaar zijn. Alleen in de browser aanroepen
 * (event handlers, effects of state-initializers van client-only componenten).
 */

export function readUrlParam(key: string): string | null {
  if (typeof window === "undefined") return null
  return new URLSearchParams(window.location.search).get(key)
}

/** Zet of verwijder (bij `null`) query-parameters zonder navigatie of herladen. */
export function writeUrlParams(params: Record<string, string | null>) {
  if (typeof window === "undefined") return
  const url = new URL(window.location.href)
  for (const [key, value] of Object.entries(params)) {
    if (value === null) url.searchParams.delete(key)
    else url.searchParams.set(key, value)
  }
  window.history.replaceState(window.history.state, "", url)
}

/** Waarde uit de URL als die in `allowed` zit, anders `fallback`. */
export function readUrlChoice<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  const value = readUrlParam(key)
  return allowed.includes(value as T) ? (value as T) : fallback
}
