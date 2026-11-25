// Zonder "use client": dient ook als Suspense-fallback in de servercomponent van de route.

import { Skeleton } from "@/components/ui/skeleton"

/** Eerste lading van het Bureau-overzicht: kop, twee tegels, signalen en de klantentabel. */
export function BureauSkeleton() {
  return (
    <div aria-busy="true" aria-label="Bureau-overzicht laden" className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-2">
          <Skeleton className="h-3 w-16" />
          <Skeleton className="h-8 w-56" />
          <Skeleton className="h-4 w-96 max-w-full" />
        </div>
        <Skeleton className="h-8 w-44" />
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        {Array.from({ length: 2 }, (_, index) => (
          <div key={index} className="flex flex-col gap-2.5 rounded-xl border bg-card px-5 py-[18px]">
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-8 w-12" />
            <Skeleton className="h-3 w-36" />
          </div>
        ))}
      </div>

      <div className="flex flex-col gap-4 rounded-xl border bg-card px-6 py-5">
        <div className="space-y-2">
          <Skeleton className="h-5 w-40" />
          <Skeleton className="h-3.5 w-[28rem] max-w-full" />
        </div>
        {Array.from({ length: 3 }, (_, index) => (
          <Skeleton key={index} className="h-12 w-full opacity-60" />
        ))}
      </div>

      <div className="flex flex-col gap-4 rounded-xl border bg-card px-6 py-5">
        <div className="space-y-2">
          <Skeleton className="h-5 w-24" />
          <Skeleton className="h-3.5 w-80 max-w-full" />
        </div>
        <div className="space-y-1">
          <Skeleton className="h-8 w-full" />
          {Array.from({ length: 5 }, (_, index) => (
            <Skeleton key={index} className="h-10 w-full opacity-60" />
          ))}
        </div>
      </div>
    </div>
  )
}
