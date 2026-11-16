/** `searchParams` zoals een Next-pagina die (na `await`) krijgt. */
export type PageSearchParams = { [key: string]: string | string[] | undefined }

/**
 * Zet `searchParams` terug om naar een query-string ("?a=1&b=2", of "" als er
 * niets is), zodat een redirect-pagina alle parameters ongewijzigd meeneemt.
 * Herhaalde parameters (`?a=1&a=2`) blijven herhaald. Werkt op server en client.
 */
export function toQueryString(params: PageSearchParams): string {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined) continue
    for (const item of Array.isArray(value) ? value : [value]) query.append(key, item)
  }
  const result = query.toString()
  return result ? `?${result}` : ""
}
