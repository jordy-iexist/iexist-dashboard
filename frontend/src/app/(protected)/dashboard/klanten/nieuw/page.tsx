import Link from "next/link"

import { NieuweKlantForm } from "@/components/klanten/NieuweKlantForm"

export const metadata = {
  title: "Klant toevoegen",
}

export default function NieuweKlantPage() {
  return (
    <div className="mx-auto w-full max-w-3xl space-y-6">
      <div className="space-y-2">
        <Link
          href="/dashboard/klanten"
          className="text-sm text-muted-foreground underline underline-offset-4 hover:text-foreground"
        >
          Terug naar klanten
        </Link>
        <h1 className="text-3xl font-bold tracking-tight">Klant toevoegen</h1>
        <p className="text-muted-foreground">
          Maak een nieuwe klant aan en vul meteen het profiel in.
        </p>
      </div>

      <NieuweKlantForm />
    </div>
  )
}
