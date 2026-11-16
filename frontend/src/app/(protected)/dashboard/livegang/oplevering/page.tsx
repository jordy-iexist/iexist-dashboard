import { LivegangOverview } from "@/components/livegang/LivegangOverview"

export const metadata = {
  title: "Livegang",
}

export default function LivegangOpleveringPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Livegang</h1>
        <p className="text-muted-foreground">
          Checklist voor de dag dat een nieuwe website live gaat: controleer op het live domein HTTPS en redirects,
          restanten van de testomgeving, tracking en formulieren. Anders dan de SEO/GEO-scan is er geen nulmeting
          nodig, dus deze werkt ook voor een gloednieuwe klantsite.
        </p>
      </div>
      <LivegangOverview variant="golive" />
    </div>
  )
}
