"use client"

import { useTransition } from "react"
import { useRouter } from "next/navigation"
import { AlertTriangle, Info, Loader2, RefreshCw } from "lucide-react"

import { PropertyPicker } from "@/components/klanten/search-console/PropertyPicker"
import { Button } from "@/components/ui/button"
import type { SearchConsoleState } from "@/lib/search-console-insights"
import { cn } from "@/lib/utils"

type NoticeState = Exclude<SearchConsoleState, "ok">

const NOTICES: Record<NoticeState, { title: string; text: string; tone: "neutral" | "amber" | "red" }> = {
  no_property: {
    title: "Geen Search Console-property gevonden",
    text: "Deze site staat niet in Search Console, of het Google-account van het bureau heeft er geen toegang toe. Kies hieronder een property; daarna verschijnen de cijfers direct.",
    tone: "neutral",
  },
  property_inaccessible: {
    title: "Geen toegang tot de gekozen property",
    text: "Het Google-account heeft geen toegang (meer) tot de gekozen property. Geef het account toegang in Search Console of kies hieronder een andere property.",
    tone: "amber",
  },
  not_configured: {
    title: "Search Console is niet gekoppeld",
    text: "De koppeling ontbreekt in de backend-configuratie. Zet GSC_CLIENT_ID, GSC_CLIENT_SECRET en GSC_REFRESH_TOKEN in de backend.",
    tone: "neutral",
  },
  token_expired: {
    title: "Toegang tot Google is verlopen",
    text: "Het token van het Google-account is verlopen of ingetrokken. Draai scripts/gsc_authorize.py opnieuw en zet het nieuwe GSC_REFRESH_TOKEN in de backend.",
    tone: "amber",
  },
  error: {
    title: "De cijfers konden niet worden opgehaald",
    text: "Search Console gaf een fout of de backend reageerde niet. Probeer het opnieuw.",
    tone: "red",
  },
}

const TONE_CLASSES = {
  neutral: "border-border",
  amber: "border-amber-400 dark:border-amber-500/60",
  red: "border-red-300 dark:border-red-500/60",
} as const

const ICON_CLASSES = {
  neutral: "text-muted-foreground",
  amber: "text-amber-600 dark:text-amber-400",
  red: "text-red-700 dark:text-red-400",
} as const

/** Kaart in plaats van de cijfers als Search Console (nog) niets kan leveren. */
export function SearchConsoleNotice({
  state,
  message,
  customerId,
}: {
  state: NoticeState
  message: string | null
  customerId: string
}) {
  const router = useRouter()
  const [refreshing, startRefresh] = useTransition()
  const notice = NOTICES[state]
  const Icon = notice.tone === "neutral" ? Info : AlertTriangle
  const showPicker = state === "no_property" || state === "property_inaccessible"
  // Bij een fout is de melding van de backend (meestal die van Google) de uitleg zelf;
  // bij de andere toestanden staat hij als extra regel onder de vaste uitleg.
  const text = state === "error" && message ? message : notice.text
  // Zegt de backend hetzelfde als de vaste uitleg, dan niet dubbel tonen.
  const detail = state !== "error" && message && !notice.text.includes(message) ? message : null

  return (
    <section
      aria-labelledby="search-console-melding"
      role={state === "error" ? "alert" : undefined}
      className={cn("space-y-4 rounded-xl border border-dashed bg-card px-6 py-5", TONE_CLASSES[notice.tone])}
    >
      <div className="flex items-start gap-3">
        <Icon className={cn("mt-0.5 size-5 shrink-0", ICON_CLASSES[notice.tone])} aria-hidden="true" />
        <div className="min-w-0 space-y-1">
          <h2 id="search-console-melding" className="text-base font-semibold">
            {notice.title}
          </h2>
          <p className="text-sm text-muted-foreground">{text}</p>
          {detail && <p className="text-xs break-words text-muted-foreground">{detail}</p>}
        </div>
      </div>

      {showPicker && <PropertyPicker customerId={customerId} />}

      {state === "error" && (
        <Button
          variant="outline"
          disabled={refreshing}
          onClick={() => startRefresh(() => router.refresh())}
        >
          {refreshing ? <Loader2 className="animate-spin" /> : <RefreshCw />}
          Opnieuw proberen
        </Button>
      )}
    </section>
  )
}
