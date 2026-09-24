import { WordPressSitesSettings } from "@/components/settings/WordPressSitesSettings"
import { SettingsPageHeader } from "@/components/settings/SettingsSection"

export const metadata = {
  title: "WordPress sites · Instellingen",
}

export default function WordPressSettingsPage() {
  return (
    <div className="space-y-8">
      <SettingsPageHeader
        title="WordPress sites"
        description="Voeg WordPress sites toe met URL, login en wachtwoord zodat het team blogs kan publiceren."
      />
      <WordPressSitesSettings />
    </div>
  )
}
