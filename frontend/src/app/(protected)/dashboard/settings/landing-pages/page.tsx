import { LandingPageSettings } from "@/components/settings/LandingPageSettings"
import { SettingsPageHeader } from "@/components/settings/SettingsSection"

export const metadata = {
  title: "Landingspagina's · Instellingen",
}

export default function LandingPageSettingsPage() {
  return (
    <div className="space-y-8">
      <SettingsPageHeader
        title="Landingspagina's"
        description="AI-instellingen voor landingspagina generatie. Lege velden gebruiken de systeemstandaard."
      />
      <LandingPageSettings />
    </div>
  )
}
