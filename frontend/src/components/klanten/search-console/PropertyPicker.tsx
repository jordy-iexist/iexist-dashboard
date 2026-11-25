"use client"

import { useRouter } from "next/navigation"

import { SearchConsoleSetting } from "@/components/livegang/SearchConsoleSetting"

/**
 * De bestaande property-kiezer, met de pagina opnieuw laten renderen na een keuze, zodat de
 * cijfers van de nieuwe property direct verschijnen.
 */
export function PropertyPicker({ customerId }: { customerId: string }) {
  const router = useRouter()
  return (
    <div className="rounded-lg border bg-card px-4 py-3 text-sm">
      <SearchConsoleSetting
        customerId={customerId}
        note="Na het opslaan worden de cijfers van deze property direct opgehaald. De keuze geldt ook voor de kwartaalscan."
        onChanged={() => router.refresh()}
      />
    </div>
  )
}
