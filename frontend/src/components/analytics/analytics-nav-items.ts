import { BarChart3, GitCompareArrows, LayoutDashboard, type LucideIcon } from "lucide-react"

export const ANALYTICS_BASE_URL = "/dashboard/livegang/analytics"

export type AnalyticsNavItem = {
  title: string
  description: string
  href: string
  icon: LucideIcon
  /** Alleen actief op precies deze URL (het overzicht); anders ook op onderliggende pagina's. */
  exact?: boolean
}

/** Sub-pagina's van Analytics. Live view komt later als één extra regel (+ map `live/`). */
export const analyticsNavItems: AnalyticsNavItem[] = [
  {
    title: "Overzicht",
    description: "Kerncijfers, rapporten en vergelijken van deze klant",
    href: ANALYTICS_BASE_URL,
    icon: LayoutDashboard,
    exact: true,
  },
  {
    title: "Rapporten",
    description: "Vaste grafiekrapporten per klant",
    href: `${ANALYTICS_BASE_URL}/rapporten`,
    icon: BarChart3,
  },
  {
    title: "Vergelijken",
    description: "Trend en scan tegen scan",
    href: `${ANALYTICS_BASE_URL}/vergelijken`,
    icon: GitCompareArrows,
  },
]
