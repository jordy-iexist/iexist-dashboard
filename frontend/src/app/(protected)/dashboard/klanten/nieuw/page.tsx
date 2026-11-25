import { NieuweKlant } from "@/components/klanten/profiel/NieuweKlant"

export const metadata = {
  title: "Klant toevoegen",
}

// Zelfde scherm als het klantprofiel: de klant wordt in één stap met het hele profiel aangemaakt.
export default function NieuweKlantPage() {
  return <NieuweKlant />
}
