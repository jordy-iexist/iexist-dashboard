import { ArrowRight, Loader2 } from "lucide-react"

import { formatEuro, formatNumber } from "@/components/klanten/analyses/wizard-model"
import { Button } from "@/components/ui/button"
import type { Estimate } from "@/lib/competitor-analysis"

/**
 * Balk onderaan de wizard: wat er geanalyseerd wordt, de live schatting en "Start analyse".
 * De knop is een submit-knop van het formulier eromheen.
 */
export function EstimateBar({
  keywords,
  topN,
  estimate,
  aiConfigured,
  disabled,
  submitting,
}: {
  /** Aantal ingevulde (unieke) zoekwoorden. */
  keywords: number
  topN: number
  estimate: Estimate
  aiConfigured: boolean
  /** Starten kan niet (bijv. Ahrefs niet ingesteld); de reden staat elders op de pagina. */
  disabled: boolean
  submitting: boolean
}) {
  const minutes = Math.max(1, Math.round(estimate.seconds / 60))
  const noun = keywords === 1 ? "zoekwoord" : "zoekwoorden"

  return (
    <div className="flex flex-col gap-4 rounded-xl bg-primary px-6 py-5 text-primary-foreground sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0 space-y-1" aria-live="polite">
        {keywords === 0 ? (
          <p className="text-base font-semibold">Kies minstens één zoekwoord om te starten</p>
        ) : (
          <p className="text-base font-semibold">
            {formatNumber(keywords)} {noun} × top {topN} (+ eigen pagina) = {formatNumber(estimate.pages)}{" "}
            pagina&apos;s om te analyseren
          </p>
        )}
        <p className="text-sm opacity-80">
          Geschatte duur ± {formatNumber(minutes)} min · Ahrefs-API ± {formatNumber(estimate.ahrefs_units)} units ·{" "}
          {aiConfigured ? `Claude ± ${formatEuro(estimate.ai_cost_eur)}` : "Claude niet ingesteld"}
        </p>
      </div>
      <Button
        type="submit"
        variant="outline"
        size="lg"
        className="shrink-0 font-semibold"
        disabled={disabled || submitting}
        aria-busy={submitting || undefined}
      >
        {submitting ? (
          <>
            <Loader2 className="animate-spin" aria-hidden />
            Bezig met starten…
          </>
        ) : (
          <>
            Start analyse
            <ArrowRight aria-hidden />
          </>
        )}
      </Button>
    </div>
  )
}
