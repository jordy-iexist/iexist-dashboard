import { Suspense } from "react"

import { BureauOverviewPage } from "@/components/bureau/BureauOverviewPage"
import { BureauSkeleton } from "@/components/bureau/BureauSkeleton"

export const metadata = {
  title: "Bureau-overzicht",
}

export default function BureauPage() {
  return (
    <Suspense fallback={<BureauSkeleton />}>
      <BureauOverviewPage />
    </Suspense>
  )
}
