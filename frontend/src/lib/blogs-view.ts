// Gedeelde constante/typen voor de onthouden weergave (kaarten of lijst) op de
// blogpagina. Vrij van `next/headers` zodat de client-component dit kan
// importeren. De server-only lezer staat in `blogs-view.server.ts`.

export const BLOGS_VIEW_COOKIE = "blogs_view"

export type BlogsView = "grid" | "list"
