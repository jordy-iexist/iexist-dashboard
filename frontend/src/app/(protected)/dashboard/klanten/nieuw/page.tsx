import { KlantHero } from "@/components/klanten/KlantHero"
import { NieuweKlantForm } from "@/components/klanten/NieuweKlantForm"

export const metadata = {
  title: "Klant toevoegen",
}

export default function NieuweKlantPage() {
  return (
    <div className="mx-auto w-full max-w-5xl space-y-8">
      <KlantHero title="Klant toevoegen">
        <p className="max-w-xl text-lg text-muted-foreground">
          Maak een nieuwe klant aan en vul meteen het profiel in.
        </p>
      </KlantHero>

      <NieuweKlantForm />
    </div>
  )
}
