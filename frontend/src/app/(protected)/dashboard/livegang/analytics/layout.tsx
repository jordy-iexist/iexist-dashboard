import { Suspense } from "react"

import { AnalyticsNav } from "@/components/analytics/AnalyticsNav"

export default function AnalyticsLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="space-y-6">
      <div className="space-y-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Analytics</h1>
          <p className="text-muted-foreground">
            Hoe een klant zich ontwikkelt over de nulmeting en de kwartaalscans heen: actiepunten, zichtbaarheid,
            autoriteit, AI-vindbaarheid en techniek.
          </p>
        </div>
        {/* AnalyticsNav leest de query-string (klant gaat mee naar de andere tab). */}
        <Suspense fallback={<div className="h-[38px] border-b" />}>
          <AnalyticsNav />
        </Suspense>
      </div>
      {children}
    </div>
  )
}
