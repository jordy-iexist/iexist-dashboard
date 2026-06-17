// Gedeelde constante/typen voor het onthouden datumfilter. Bewust vrij van
// `next/headers` zodat zowel de client-component als de server dit kunnen
// importeren. De server-only lezer staat in `blogs-date-filter.server.ts`.

export const BLOGS_CREATED_DATE_COOKIE = "blogs_created_date"

export type CreatedDateParams = {
  createdOn: string | null
  createdFrom: string | null
  createdTo: string | null
}
