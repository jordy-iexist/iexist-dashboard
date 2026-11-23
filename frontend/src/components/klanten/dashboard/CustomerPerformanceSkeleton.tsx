import { Skeleton } from "@/components/ui/skeleton"

// Volgt de vorm van de KPI-rij en de Quick wins-card terwijl Pro Rank Tracker laadt.
export function CustomerPerformanceSkeleton() {
  return (
    <div className="space-y-6" aria-busy="true" aria-label="Posities laden">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }, (_, index) => (
          <div key={index} className="flex flex-col gap-2.5 rounded-xl border bg-card px-5 py-[18px]">
            <Skeleton className="h-4 w-36" />
            <Skeleton className="h-8 w-16" />
            <Skeleton className="h-3 w-40" />
          </div>
        ))}
      </div>

      <div className="flex flex-col gap-4 rounded-xl border bg-card px-6 py-5">
        <div className="space-y-2">
          <Skeleton className="h-5 w-80 max-w-full" />
          <Skeleton className="h-3.5 w-96 max-w-full" />
        </div>
        <div className="space-y-1">
          <Skeleton className="h-8 w-full" />
          {Array.from({ length: 6 }, (_, index) => (
            <Skeleton key={index} className="h-10 w-full opacity-60" />
          ))}
        </div>
        <div className="flex items-center justify-between">
          <Skeleton className="h-4 w-44" />
          <Skeleton className="h-9 w-40 rounded-full" />
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {Array.from({ length: 2 }, (_, index) => (
          <div key={index} className="flex flex-col gap-4 rounded-xl border bg-card px-6 py-5">
            <Skeleton className="h-5 w-56 max-w-full" />
            {Array.from({ length: 3 }, (_, row) => (
              <Skeleton key={row} className="h-10 w-full opacity-60" />
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}
