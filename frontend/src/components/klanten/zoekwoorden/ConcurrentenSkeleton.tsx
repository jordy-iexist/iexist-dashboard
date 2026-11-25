import { Skeleton } from "@/components/ui/skeleton"

/**
 * Volgt de vorm van de KPI-rij, de concurrententabel en de heatmap met de AI-kaart, terwijl het
 * overzicht voor het eerst wordt opgehaald of de eerste verversing loopt.
 */
export function ConcurrentenSkeleton({ label = "Concurrenten laden" }: { label?: string }) {
  return (
    <div className="space-y-6" aria-busy="true" aria-label={label}>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }, (_, index) => (
          <div key={index} className="flex flex-col gap-2.5 rounded-xl border bg-card px-5 py-[18px]">
            <Skeleton className="h-4 w-36 max-w-full" />
            <Skeleton className="h-8 w-20" />
            <Skeleton className="h-3 w-32 max-w-full" />
          </div>
        ))}
      </div>

      <div className="flex flex-col gap-4 rounded-xl border bg-card px-6 py-5">
        <div className="space-y-2">
          <Skeleton className="h-5 w-64 max-w-full" />
          <Skeleton className="h-3.5 w-[30rem] max-w-full" />
        </div>
        <div className="space-y-1">
          <Skeleton className="h-8 w-full" />
          {Array.from({ length: 6 }, (_, index) => (
            <Skeleton key={index} className="h-11 w-full opacity-60" />
          ))}
        </div>
      </div>

      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="flex flex-col gap-4 rounded-xl border bg-card px-6 py-5">
          <Skeleton className="h-5 w-48 max-w-full" />
          {Array.from({ length: 5 }, (_, row) => (
            <Skeleton key={row} className="h-9 w-full opacity-60" />
          ))}
        </div>
        <div className="flex flex-col gap-4 rounded-xl border bg-card px-6 py-5">
          <Skeleton className="h-5 w-40 max-w-full" />
          <Skeleton className="h-28 w-full opacity-60" />
          <Skeleton className="h-4 w-full opacity-60" />
          <Skeleton className="h-4 w-5/6 opacity-60" />
          <Skeleton className="h-4 w-4/6 opacity-60" />
        </div>
      </div>
    </div>
  )
}
