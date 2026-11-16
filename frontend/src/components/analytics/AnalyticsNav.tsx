"use client"

import Link from "next/link"
import { usePathname, useSearchParams } from "next/navigation"

import { analyticsNavItems } from "@/components/analytics/analytics-nav-items"
import { cn } from "@/lib/utils"

/** Horizontale tabs van Analytics (stijl van `PanelTabs`); de gekozen klant gaat mee. */
export function AnalyticsNav() {
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const klant = searchParams.get("klant")
  const query = klant ? `?klant=${encodeURIComponent(klant)}` : ""

  return (
    <nav aria-label="Analytics" className="flex gap-1 overflow-x-auto border-b">
      {analyticsNavItems.map((item) => {
        const isActive = item.exact
          ? pathname === item.href
          : pathname === item.href || pathname.startsWith(`${item.href}/`)
        return (
          <Link
            key={item.href}
            href={`${item.href}${query}`}
            aria-current={isActive ? "page" : undefined}
            title={item.description}
            className={cn(
              "-mb-px inline-flex items-center gap-1.5 whitespace-nowrap border-b-2 px-4 py-2 text-sm transition-colors",
              isActive
                ? "border-primary font-medium text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground"
            )}
          >
            <item.icon className="size-4" />
            {item.title}
          </Link>
        )
      })}
    </nav>
  )
}
