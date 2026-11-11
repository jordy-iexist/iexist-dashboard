"use client"

import ReactMarkdown from "react-markdown"
import { Check, ChevronDown, Copy, ExternalLink, Loader2, RotateCcw, X } from "lucide-react"
import { useState } from "react"

import { Button } from "@/components/ui/button"
import { Pill } from "@/components/livegang/shared"
import {
  SUGGESTION_STATUS_LABELS,
  updateSuggestionStatus,
  type ContentSuggestion,
  type SuggestionStatus,
} from "@/lib/launch-checklist"
import { cn } from "@/lib/utils"

function plain(text: string) {
  return text.replace(/[*_#`>\[\]]/g, "").replace(/\s+/g, " ").trim()
}

/**
 * Eén AI-voorstel als regel in een lijst: ingeklapt alleen titel + korte
 * preview en de knoppen, uitgeklapt huidig → voorstel met toelichting.
 * Gebruik binnen een `<ul className="divide-y …">`.
 *
 * `flat`: altijd open, zonder inspringing of gekleurd vak — voor gebruik in
 * een paneel waar het voorstel direct zichtbaar moet zijn.
 */
export function SuggestionRow({
  suggestion,
  markdown = false,
  preview,
  defaultOpen = false,
  flat = false,
  onChanged,
}: {
  suggestion: ContentSuggestion
  /** Voorstel als markdown tonen (contentgap-opzetten). */
  markdown?: boolean
  /** Eigen samenvatting voor de ingeklapte regel; standaard het begin van het voorstel. */
  preview?: React.ReactNode
  defaultOpen?: boolean
  /** Altijd open en zonder kaart/inspringing tonen. */
  flat?: boolean
  onChanged: (next: ContentSuggestion) => void
}) {
  const [open, setOpen] = useState(defaultOpen)
  const [busy, setBusy] = useState(false)
  const [copied, setCopied] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const ref = suggestion.details?.ref
  const handled = suggestion.status !== "open"
  const title = suggestion.title || plain(suggestion.proposed_value).slice(0, 80)

  async function setStatus(status: SuggestionStatus) {
    setBusy(true)
    setError(null)
    try {
      onChanged(await updateSuggestionStatus(suggestion.id, status))
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(suggestion.proposed_value)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      setError("Kopiëren is niet gelukt.")
    }
  }

  const actions = (
    <>
      {handled && (
        <Pill tone={suggestion.status === "overgenomen" ? "green" : "muted"}>
          {SUGGESTION_STATUS_LABELS[suggestion.status]}
        </Pill>
      )}
      <div className="flex shrink-0 items-center">
        <Button size="icon" variant="ghost" className="size-8" title="Kopieer voorstel" aria-label="Kopieer voorstel" onClick={() => void copy()}>
          {copied ? <Check className="text-green-600" /> : <Copy />}
        </Button>
        {handled ? (
          <Button size="icon" variant="ghost" className="size-8" title="Heropenen" aria-label="Heropenen" disabled={busy} onClick={() => void setStatus("open")}>
            {busy ? <Loader2 className="animate-spin" /> : <RotateCcw />}
          </Button>
        ) : (
          <>
            <Button size="icon" variant="ghost" className="size-8" title="Markeer als overgenomen" aria-label="Markeer als overgenomen" disabled={busy} onClick={() => void setStatus("overgenomen")}>
              {busy ? <Loader2 className="animate-spin" /> : <Check />}
            </Button>
            <Button size="icon" variant="ghost" className="size-8" title="Afwijzen" aria-label="Afwijzen" disabled={busy} onClick={() => void setStatus("afgewezen")}>
              <X />
            </Button>
          </>
        )}
      </div>
    </>
  )

  const proposed = markdown ? (
    <div className="prose prose-sm max-w-none [overflow-wrap:anywhere] dark:prose-invert">
      <ReactMarkdown>{suggestion.proposed_value}</ReactMarkdown>
    </div>
  ) : (
    <p className="whitespace-pre-wrap [overflow-wrap:anywhere]">{suggestion.proposed_value}</p>
  )

  const sizeInfo =
    suggestion.details?.length != null ? `${suggestion.details.length} tekens · ±${suggestion.details.pixels} px` : null

  const refLink = ref && /^https?:\/\//.test(ref) && (
    <a
      href={ref}
      target="_blank"
      rel="noreferrer noopener"
      className="inline-flex max-w-full items-center gap-1 text-xs text-primary hover:underline"
    >
      <span className="truncate">{ref}</span>
      <ExternalLink className="size-3 shrink-0" />
    </a>
  )

  if (flat) {
    return (
      <li className="space-y-2 py-3">
        <div className="flex items-start gap-2">
          <p
            className={cn(
              "min-w-0 flex-1 pt-1.5 text-sm font-medium",
              handled && "text-muted-foreground",
              suggestion.status === "afgewezen" && "line-through"
            )}
          >
            {title}
          </p>
          {actions}
        </div>
        <dl className={cn("grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[5.5rem_1fr]", handled && "opacity-60")}>
          {suggestion.current_value && (
            <>
              <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground sm:pt-0.5">Huidig</dt>
              <dd className="min-w-0 whitespace-pre-wrap [overflow-wrap:anywhere] text-muted-foreground">
                {suggestion.current_value}
              </dd>
            </>
          )}
          <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground sm:pt-0.5">Voorstel</dt>
          <dd className="min-w-0">
            {proposed}
            {sizeInfo && <p className="mt-0.5 text-xs text-muted-foreground">{sizeInfo}</p>}
          </dd>
          {suggestion.rationale && (
            <>
              <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground sm:pt-0.5">Waarom</dt>
              <dd className="min-w-0 text-xs text-muted-foreground sm:pt-0.5">{suggestion.rationale}</dd>
            </>
          )}
        </dl>
        {refLink}
        {error && <p className="text-xs text-red-700">{error}</p>}
      </li>
    )
  }

  return (
    <li className={cn(handled && "bg-muted/20")}>
      <div className="flex items-center gap-2 px-3 py-2">
        <button
          type="button"
          onClick={() => setOpen(!open)}
          aria-expanded={open}
          className="flex min-w-0 flex-1 items-center gap-2 text-left"
        >
          <ChevronDown className={cn("size-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")} />
          <span className={cn("min-w-0 flex-1", handled && "opacity-60")}>
            <span className={cn("block truncate text-sm font-medium", suggestion.status === "afgewezen" && "line-through")}>
              {title}
            </span>
            {!open && (
              <span className="block truncate text-xs text-muted-foreground">
                {preview ?? plain(suggestion.proposed_value)}
              </span>
            )}
          </span>
        </button>
        {actions}
      </div>

      {open && (
        <div className="space-y-3 px-3 pb-3 pl-9">
          {suggestion.current_value && (
            <div className="text-sm">
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Huidig</p>
              <p className="whitespace-pre-wrap [overflow-wrap:anywhere] text-muted-foreground">{suggestion.current_value}</p>
            </div>
          )}
          <div className="rounded-md bg-primary/5 px-3 py-2 text-sm">
            <p className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Voorstel
              {sizeInfo && <span className="normal-case tracking-normal">· {sizeInfo}</span>}
            </p>
            {proposed}
          </div>
          {suggestion.rationale && (
            <p className="text-xs text-muted-foreground">
              <span className="font-medium">Waarom:</span> {suggestion.rationale}
            </p>
          )}
          {refLink}
        </div>
      )}
      {error && <p className="px-3 pb-2 pl-9 text-xs text-red-700">{error}</p>}
    </li>
  )
}
