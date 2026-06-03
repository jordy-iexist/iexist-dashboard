import { LandingPageUploadTabs } from "@/components/landing-pages/LandingPageUploadTabs"
import { RecentLandingPageUploads } from "@/components/landing-pages/RecentLandingPageUploads"

export const metadata = { title: "Landingspagina's aanmaken" }

export default function LandingPagesUploadPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Landingspagina&apos;s aanmaken</h1>
        <p className="text-muted-foreground">Upload een CSV bestand of vul rijen handmatig in om landingspagina&apos;s te genereren</p>
      </div>
      <div className="rounded-lg border p-4 sm:p-6 md:p-8">
        <LandingPageUploadTabs />
      </div>
      <RecentLandingPageUploads />
    </div>
  )
}
