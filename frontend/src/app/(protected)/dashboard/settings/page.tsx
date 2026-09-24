import Link from "next/link"
import { ChevronRight } from "lucide-react"

import { settingsNavGroups } from "@/components/settings/settings-nav-items"

export const metadata = {
  title: "Instellingen",
}

export default function SettingsPage() {
  return (
    <div className="space-y-8">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Instellingen</h1>
        <p className="text-sm text-muted-foreground">
          Beheer je account, integraties en content generatie.
        </p>
      </div>

      {settingsNavGroups.map((group) => (
        <div key={group.title} className="space-y-2">
          <h2 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {group.title}
          </h2>
          <ul className="divide-y border-y">
            {group.items.map((item) => (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className="flex items-center gap-4 px-2 py-3 transition-colors hover:bg-muted/50"
                >
                  <item.icon className="size-4 shrink-0 text-muted-foreground" />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium">{item.title}</p>
                    <p className="truncate text-sm text-muted-foreground">
                      {item.description}
                    </p>
                  </div>
                  <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
                </Link>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  )
}
