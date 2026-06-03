import { LandingPageCsvUpload } from "@/components/landing-pages/LandingPageCsvUpload"
import { RecentLandingPageUploads } from "@/components/landing-pages/RecentLandingPageUploads"

export const metadata = { title: "Landingspagina's Uploaden" }

export default function LandingPagesUploadPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Landingspagina&apos;s uploaden</h1>
        <p className="text-muted-foreground">Upload een CSV bestand om landingspagina&apos;s te genereren</p>
      </div>
      <div className="rounded-lg border p-4 sm:p-6 md:p-8">
        <LandingPageCsvUpload />
      </div>
      <RecentLandingPageUploads />
    </div>
  )
}
