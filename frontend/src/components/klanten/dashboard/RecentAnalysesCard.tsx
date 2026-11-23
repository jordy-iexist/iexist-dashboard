import Link from "next/link"
import { Plus } from "lucide-react"

import { AnalysisStatusPill } from "@/components/klanten/analyses/AnalysisStatusPill"
import { Button } from "@/components/ui/button"
import {
  analysesHref,
  analysisHref,
  formatAnalysisDate,
  formatKeywords,
  newAnalysisHref,
} from "@/lib/competitor-analysis"
import type { RecentAnalyses } from "@/lib/competitor-analysis.server"

// De laatste concurrentieanalyses van deze klant, met links naar het resultaat en de wizard.
export function RecentAnalysesCard({
  customerId,
  analyses,
}: {
  customerId: string
  analyses: RecentAnalyses
}) {
  const { items, failed } = analyses

  return (
    <section
      aria-labelledby="recent-analyses-title"
      className="flex flex-col gap-4 rounded-xl border bg-card px-6 py-5"
    >
      <div className="flex items-center justify-between gap-3">
        <h2 id="recent-analyses-title" className="text-base font-semibold">
          Recente analyses
        </h2>
        <Link
          href={analysesHref(customerId)}
          className="text-[13px] font-semibold whitespace-nowrap underline-offset-2 hover:underline"
        >
          Alle analyses
        </Link>
      </div>

      {items.length === 0 ? (
        <p className="rounded-lg border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
          {failed
            ? "De analyses konden niet worden opgehaald. Probeer het later opnieuw."
            : "Nog geen analyses. Vergelijk de pagina's van deze klant met de top van Google via een concurrentieanalyse."}
        </p>
      ) : (
        <ul>
          {items.map((item) => (
            <li key={item.id} className="border-b">
              <Link
                href={analysisHref(customerId, item.id)}
                className="flex items-center gap-3 py-2.5 hover:bg-muted/40"
              >
                <div className="min-w-0 flex-1 space-y-0.5">
                  <p className="truncate text-sm font-semibold" title={item.keywords.join(", ")}>
                    {formatKeywords(item.keywords, item.total_keywords)}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {[formatAnalysisDate(item.created_at), `top ${item.top_n}`]
                      .filter(Boolean)
                      .join(" · ")}
                  </p>
                </div>
                <AnalysisStatusPill status={item.status} />
              </Link>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-auto flex justify-end">
        <Button asChild variant="outline" size="sm" className="font-semibold">
          <Link href={newAnalysisHref(customerId)}>
            <Plus />
            Nieuwe analyse
          </Link>
        </Button>
      </div>
    </section>
  )
}
