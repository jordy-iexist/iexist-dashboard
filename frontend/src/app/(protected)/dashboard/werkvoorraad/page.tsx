import { Suspense } from "react"

import { BoardSkeleton } from "@/components/werkvoorraad/parts"
import { WorkBoardPage } from "@/components/werkvoorraad/WorkBoardPage"
import { getCurrentUser } from "@/lib/auth"

export const metadata = {
  title: "Werkvoorraad",
}

export default async function WerkvoorraadPage() {
  // `id` uit /api/auth/me is het id van de tabel users, net als de medewerkers op het bord.
  const user = await getCurrentUser()
  return (
    // Suspense is nodig: het bord leest `useSearchParams()`, anders breekt de productiebuild.
    <Suspense fallback={<BoardSkeleton />}>
      <WorkBoardPage currentUserId={user?.id ?? null} />
    </Suspense>
  )
}
