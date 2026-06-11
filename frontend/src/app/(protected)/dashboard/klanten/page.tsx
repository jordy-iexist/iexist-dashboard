import { KlantenManager } from "@/components/klanten/KlantenManager"

export const metadata = {
  title: "Klanten",
}

export default function KlantenPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Klanten</h1>
        <p className="text-muted-foreground">
          Beheer de klanten waaraan blogs, landingspagina&apos;s en SEO-tools
          gekoppeld worden.
        </p>
      </div>

      <KlantenManager />
    </div>
  )
}
