import { getCurrentUser } from "@/lib/auth"
import { redirect } from "next/navigation"
import { OpenAISettings } from "@/components/settings/OpenAISettings"
import { WordPressSitesSettings } from "@/components/settings/WordPressSitesSettings"

export const metadata = {
  title: "Instellingen",
}

export default async function SettingsPage() {
  const user = await getCurrentUser()

  if (!user) {
    redirect("/login")
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Instellingen</h1>
        <p className="text-muted-foreground">
          Beheer je account instellingen
        </p>
      </div>

      <div className="space-y-6">
        <div className="rounded-lg border p-6">
          <h2 className="text-lg font-semibold mb-4">Profiel</h2>
          <div className="space-y-4">
            <div>
              <label className="text-sm font-medium">Email</label>
              <p className="text-sm text-muted-foreground mt-1">{user.email}</p>
            </div>
            <div>
              <label className="text-sm font-medium">Gebruikers id</label>
              <p className="text-sm text-muted-foreground mt-1 font-mono">{user.id}</p>
            </div>
          </div>
        </div>

        <OpenAISettings />

        <WordPressSitesSettings />
      </div>
    </div>
  )
}
