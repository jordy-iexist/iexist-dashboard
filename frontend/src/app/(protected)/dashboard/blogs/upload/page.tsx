import { BlogUploadTabs } from "@/components/blogs/BlogUploadTabs"
import { RecentCsvUploads } from "@/components/blogs/RecentCsvUploads"
import { KlantHero } from "@/components/klanten/KlantHero"

export const metadata = {
  title: "Blogs aanmaken",
}

export default async function BlogsUploadPage() {
  return (
    <div className="space-y-8">
      <KlantHero backHref={null} eyebrow="Content" title="Blogs aanmaken">
        <p className="max-w-xl text-muted-foreground">
          Upload een CSV bestand of vul rijen handmatig in om blogs te genereren
        </p>
      </KlantHero>

      <BlogUploadTabs />

      <RecentCsvUploads />
    </div>
  )
}
