import { Skeleton } from "@/components/ui/skeleton"

/**
 * Volgt de vorm van de tegels, de tabel met gap-zoekwoorden en de twee kaarten eronder, terwijl
 * de content gap voor het eerst wordt opgehaald of de eerste run loopt.
 */
export function ContentGapSkeleton({ label = "Content gap laden" }: { label?: string }) {
  return (
    <div className="space-y-6" aria-busy="true" aria-label={label}>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }, (_, index) => (
          <div key={index} className="flex flex-col gap-2.5 rounded-xl border bg-card px-5 py-[18px]">
            <Skeleton className="h-4 w-32 max-w-full" />
            <Skeleton className="h-8 w-24" />
            <Skeleton className="h-3 w-28 max-w-full" />
          </div>
        ))}
      </div>

      <div className="flex flex-col gap-4 rounded-xl border bg-card px-6 py-5">
        <div className="space-y-2">
          <Skeleton className="h-5 w-40 max-w-full" />
          <Skeleton className="h-3.5 w-[28rem] max-w-full" />
        </div>
        <div className="space-y-1">
          <Skeleton className="h-8 w-full" />
          {Array.from({ length: 8 }, (_, index) => (
            <Skeleton key={index} className="h-10 w-full opacity-60" />
          ))}
        </div>
      </div>

      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_420px]">
        <div className="flex flex-col gap-4 rounded-xl border bg-card px-6 py-5">
          <Skeleton className="h-5 w-36 max-w-full" />
          {Array.from({ length: 4 }, (_, row) => (
            <Skeleton key={row} className="h-6 w-full opacity-60" />
          ))}
        </div>
        <div className="flex flex-col gap-4 rounded-xl border bg-card px-6 py-5">
          <Skeleton className="h-5 w-40 max-w-full" />
          {Array.from({ length: 4 }, (_, row) => (
            <Skeleton key={row} className="h-6 w-full opacity-60" />
          ))}
        </div>
      </div>
    </div>
  )
}
