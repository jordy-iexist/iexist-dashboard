import { SeoTracker } from "@/components/seo/SeoTracker"

export const metadata = {
  title: "SEO Tracker",
}

export default function SeoTrackerToolPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">SEO Tracker</h1>
        <p className="text-muted-foreground">
          Voeg klantwebsites toe en scan op welke zoekwoorden ze gevonden worden.
        </p>
      </div>

      <SeoTracker />
    </div>
  )
}
