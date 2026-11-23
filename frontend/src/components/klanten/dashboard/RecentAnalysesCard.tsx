import { Pill } from "@/components/livegang/shared"

// De concurrentieanalyse bestaat nog niet; tot die er is toont de card een lege toestand.
export function RecentAnalysesCard() {
  return (
    <section
      aria-labelledby="recent-analyses-title"
      className="flex flex-col gap-4 rounded-xl border bg-card px-6 py-5"
    >
      <div className="flex items-center justify-between gap-3">
        <h2 id="recent-analyses-title" className="text-base font-semibold">
          Recente analyses
        </h2>
        <Pill>Binnenkort</Pill>
      </div>
      <p className="rounded-lg border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
        Nog geen analyses. Zodra de concurrentieanalyse beschikbaar is, staan hier de laatste
        analyses van deze klant.
      </p>
    </section>
  )
}
