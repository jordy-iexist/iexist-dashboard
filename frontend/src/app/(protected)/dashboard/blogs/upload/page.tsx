import { BlogUploadTabs } from "@/components/blogs/BlogUploadTabs"
import { RecentCsvUploads } from "@/components/blogs/RecentCsvUploads"

export const metadata = {
  title: "Blogs aanmaken",
}

export default async function BlogsUploadPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Blogs aanmaken</h1>
        <p className="text-muted-foreground">
          Upload een CSV bestand of vul rijen handmatig in om blogs te genereren
        </p>
      </div>

      <div className="rounded-lg border p-4 sm:p-6 md:p-8">
        <BlogUploadTabs />
      </div>

      <RecentCsvUploads />
    </div>
  )
}
