"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"

import { cn } from "@/lib/utils"
import { settingsNavGroups } from "@/components/settings/settings-nav-items"

export function SettingsNav() {
  const pathname = usePathname()

  return (
    <nav className="space-y-6">
      {settingsNavGroups.map((group) => (
        <div key={group.title} className="space-y-1">
          <p className="px-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {group.title}
          </p>
          {group.items.map((item) => {
            const isActive = pathname === item.href
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "flex items-center gap-2 rounded-md px-3 py-1.5 text-sm transition-colors",
                  isActive
                    ? "bg-card font-medium text-foreground shadow-xs"
                    : "text-muted-foreground hover:bg-card/70 hover:text-foreground"
                )}
              >
                <item.icon className="size-4" />
                {item.title}
              </Link>
            )
          })}
        </div>
      ))}
    </nav>
  )
}
