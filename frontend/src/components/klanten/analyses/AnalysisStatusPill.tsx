import { Loader2 } from "lucide-react"

import { Pill, type Tone } from "@/components/livegang/shared"
import { ANALYSIS_STATUS_LABELS, isActive, type AnalysisStatus } from "@/lib/competitor-analysis"

export const ANALYSIS_STATUS_TONES: Record<AnalysisStatus, Tone> = {
  pending: "blue",
  serp: "blue",
  fetching: "blue",
  analyzing: "blue",
  completed: "green",
  failed: "red",
  canceled: "muted",
}

/** Status van een analyse; een lopende analyse krijgt een draaiend icoon. */
export function AnalysisStatusPill({ status, className }: { status: AnalysisStatus; className?: string }) {
  return (
    <Pill tone={ANALYSIS_STATUS_TONES[status]} className={className}>
      {isActive(status) && <Loader2 className="size-3 animate-spin" aria-hidden="true" />}
      {ANALYSIS_STATUS_LABELS[status]}
    </Pill>
  )
}
