/**
 * Kleine helpers om weergavekeuzes (fase, tabblad) in de URL te bewaren, zodat
 * ze een refresh overleven en deelbaar zijn. Alleen in de browser aanroepen
 * (event handlers, effects of state-initializers van client-only componenten).
 */

export function readUrlParam(key: string): string | null {
  if (typeof window === "undefined") return null
  return new URLSearchParams(window.location.search).get(key)
}

/**
 * Zet of verwijder (bij `null`) query-parameters zonder navigatie of herladen.
 *
 * Standaard geven we Nexts eigen history-state mee; Next ziet de wijziging dan als zijn eigen
 * en `useSearchParams()` blijft op het vorige adres staan. Met `syncRouter` krijgt de router
 * het nieuwe adres wel door (Next vult zijn state zelf aan), zodat `useSearchParams()` meeloopt.
 */
export function writeUrlParams(params: Record<string, string | null>, { syncRouter = false } = {}) {
  if (typeof window === "undefined") return
  const url = new URL(window.location.href)
  for (const [key, value] of Object.entries(params)) {
    if (value === null) url.searchParams.delete(key)
    else url.searchParams.set(key, value)
  }
  window.history.replaceState(syncRouter ? null : window.history.state, "", url)
}

/** `value` als die in `allowed` zit, anders `fallback` (bijv. met een waarde uit `useSearchParams()`). */
export function pickUrlChoice<T extends string>(value: string | null, allowed: readonly T[], fallback: T): T {
  return allowed.includes(value as T) ? (value as T) : fallback
}

/** Waarde uit de URL als die in `allowed` zit, anders `fallback`. */
export function readUrlChoice<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  return pickUrlChoice(readUrlParam(key), allowed, fallback)
}
