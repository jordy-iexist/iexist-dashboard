import { LivegangOverview } from "@/components/livegang/LivegangOverview"

export const metadata = {
  title: "Livegang checklist",
}

export default function LivegangPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Livegang checklist</h1>
        <p className="text-muted-foreground">
          Kies een klant om de livegang-checklist te doorlopen. Fase 1 (Nulmeting &amp; AI scan), fase 2
          (GEO/SEO-checklist) en fase 3 (Contentcreatie &amp; onpage optimalisatie) zijn beschikbaar; fase 4 volgt.
        </p>
      </div>
      <LivegangOverview />
    </div>
  )
}
