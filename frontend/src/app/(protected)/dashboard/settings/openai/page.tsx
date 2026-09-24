import { OpenAISettings } from "@/components/settings/OpenAISettings"
import { SettingsPageHeader } from "@/components/settings/SettingsSection"

export const metadata = {
  title: "OpenAI API key · Instellingen",
}

export default function OpenAISettingsPage() {
  return (
    <div className="space-y-8">
      <SettingsPageHeader
        title="OpenAI API key"
        description="Deze key wordt alleen voor jouw account gebruikt voor blog- en SEO-functies."
      />
      <OpenAISettings />
    </div>
  )
}
