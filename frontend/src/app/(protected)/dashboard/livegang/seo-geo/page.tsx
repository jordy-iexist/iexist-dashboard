import { LivegangOverview } from "@/components/livegang/LivegangOverview"

export const metadata = {
  title: "SEO/GEO-scan",
}

export default function LivegangPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">SEO/GEO-scan</h1>
        <p className="text-muted-foreground">
          Kies een klant om de SEO/GEO-scan te doorlopen: fase 1 (Nulmeting &amp; AI scan), fase 2
          (GEO/SEO-checklist), fase 3 (Contentcreatie &amp; onpage optimalisatie) en fase 4 (Kwartaal
          GEO-werkzaamheden, elk kwartaal een nieuwe ronde).
        </p>
      </div>
      <LivegangOverview />
    </div>
  )
}
