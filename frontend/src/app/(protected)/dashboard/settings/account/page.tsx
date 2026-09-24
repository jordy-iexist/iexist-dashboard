import { redirect } from "next/navigation"

import { getCurrentUser } from "@/lib/auth"
import {
  SettingsPageHeader,
  SettingsSection,
} from "@/components/settings/SettingsSection"

export const metadata = {
  title: "Profiel · Instellingen",
}

export default async function AccountSettingsPage() {
  const user = await getCurrentUser()

  if (!user) {
    redirect("/login")
  }

  return (
    <div className="space-y-8">
      <SettingsPageHeader title="Profiel" description="Je accountgegevens." />

      <div>
        <SettingsSection title="Account">
          <div className="space-y-1">
            <p className="text-sm font-medium">Email</p>
            <p className="text-sm text-muted-foreground">{user.email}</p>
          </div>
          <div className="space-y-1">
            <p className="text-sm font-medium">Gebruikers id</p>
            <p className="font-mono text-sm text-muted-foreground">{user.id}</p>
          </div>
        </SettingsSection>
      </div>
    </div>
  )
}
