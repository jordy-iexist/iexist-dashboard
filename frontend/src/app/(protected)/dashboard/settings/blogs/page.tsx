import { BlogGenerationSettings } from "@/components/settings/BlogGenerationSettings"
import { SettingsPageHeader } from "@/components/settings/SettingsSection"

export const metadata = {
  title: "Blogs · Instellingen",
}

export default function BlogSettingsPage() {
  return (
    <div className="space-y-8">
      <SettingsPageHeader
        title="Blogs"
        description="AI-instellingen voor blog generatie. Lege velden gebruiken de systeemstandaard."
      />
      <BlogGenerationSettings />
    </div>
  )
}
