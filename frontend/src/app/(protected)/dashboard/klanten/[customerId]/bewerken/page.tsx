import { redirect } from "next/navigation"

type KlantBewerkenPageProps = {
  params: Promise<{ customerId: string }>
}

// "Klant bewerken" is opgegaan in het klantprofiel; oude links sturen daarheen door.
export default async function KlantBewerkenPage({ params }: KlantBewerkenPageProps) {
  const { customerId } = await params
  redirect(`/dashboard/klanten/${encodeURIComponent(customerId)}/profiel`)
}
