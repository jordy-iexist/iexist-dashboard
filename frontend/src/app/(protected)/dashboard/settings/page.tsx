import Link from "next/link"
import { Building2, ChevronRight } from "lucide-react"

import {
  settingsNavGroups,
  type SettingsNavGroup,
} from "@/components/settings/settings-nav-items"
import { customerHref } from "@/lib/active-customer"
import { readActiveCustomerCookie } from "@/lib/active-customer.server"

export const metadata = {
  title: "Instellingen",
}

// Overzicht van alle instellingen. Op smal scherm is het paneel naast de
// sidebar verborgen; dan is dit het menu.
export default async function SettingsPage() {
  const customerId = await readActiveCustomerCookie()

  // Klantprofiel hoort bij de gekozen klant; zonder klant eerst naar de lijst.
  const customerGroup: SettingsNavGroup = {
    title: "Klant",
    items: [
      {
        title: "Klantprofiel",
        description:
          "Bedrijf, diensten, tone of voice en regels voor AI-content van de gekozen klant",
        href: customerId ? customerHref("profiel", customerId) : "/dashboard/klanten",
        icon: Building2,
      },
    ],
  }

  return (
    <div className="space-y-8">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Instellingen</h1>
        <p className="text-sm text-muted-foreground">
          Beheer je account, integraties en content generatie.
        </p>
      </div>

      {[...settingsNavGroups, customerGroup].map((group) => (
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
