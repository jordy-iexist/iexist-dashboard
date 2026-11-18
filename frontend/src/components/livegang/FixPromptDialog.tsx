"use client"

import { Check, Copy, Loader2, RefreshCw } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { createFixPrompt, formatDateTime, type FixPromptResponse, type LaunchScanIssue } from "@/lib/launch-checklist"

/**
 * Prompt voor Claude Code bij één actiepunt. Bij openen vraagt de dialog de prompt op: de backend
 * geeft de opgeslagen versie direct terug, of maakt er synchroon een (kan tientallen seconden duren).
 * Mount per actiepunt (met `key`), zodat elke opening met een schone staat begint.
 */
export function FixPromptDialog({
  issue,
  onClose,
  onGenerated,
}: {
  issue: LaunchScanIssue
  onClose: () => void
  /** Na een geslaagde aanroep: zodat de lijst zonder herladen toont dat er een prompt is. */
  onGenerated: (issueId: string, generatedAt: string) => void
}) {
  const [result, setResult] = useState<FixPromptResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  // Alleen het antwoord op de laatste aanvraag telt.
  const requestRef = useRef(0)
  // Eén aanvraag bij openen, ook als React (StrictMode) het effect dubbel draait: anders twee modelaanroepen.
  const startedRef = useRef(false)

  function request(regenerate: boolean) {
    const id = ++requestRef.current
    return createFixPrompt(issue.id, regenerate).then(
      (next) => {
        // Ook na sluiten doorgeven, zodat het icoon in de lijst klopt.
        onGenerated(issue.id, next.generated_at)
        if (id !== requestRef.current) return
        setResult(next)
        setError(null)
        setLoading(false)
      },
      (err: unknown) => {
        if (id !== requestRef.current) return
        setError((err as Error).message)
        setLoading(false)
      }
    )
  }

  useEffect(() => {
    if (startedRef.current) return
    startedRef.current = true
    void request(false)
    // Alleen bij openen; de dialog wordt per actiepunt opnieuw gemount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Zonder prompt (eerste aanvraag mislukt) is het een nieuwe poging; anders echt opnieuw genereren.
  const retry = !result && error !== null
  function regenerate() {
    setLoading(true)
    setError(null)
    setCopied(false)
    void request(!retry)
  }

  async function copyPrompt() {
    if (!result?.prompt) return
    try {
      await navigator.clipboard.writeText(result.prompt)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      setError("Kopiëren naar het klembord is mislukt.")
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>Prompt voor Claude Code</DialogTitle>
          <DialogDescription className="break-words">{issue.title}</DialogDescription>
        </DialogHeader>

        {loading && (
          <div className="flex items-center gap-2 rounded-md border bg-muted/30 px-3 py-6 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" />
            {result ? "Nieuwe prompt maken… dit kan even duren." : "Prompt ophalen of maken… dit kan even duren."}
          </div>
        )}

        {!loading && result && (
          <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap break-words rounded-md border bg-muted/30 p-3 font-mono text-xs">
            {result.prompt}
          </pre>
        )}

        {error && <p className="text-sm text-red-600">{error}</p>}

        <DialogFooter className="sm:items-center">
          {result && !loading && (
            <p className="text-xs text-muted-foreground sm:mr-auto">
              {result.cached ? "Opgeslagen prompt" : "Nieuw gemaakt"} · {formatDateTime(result.generated_at)}
            </p>
          )}
          <Button size="sm" variant="outline" disabled={loading} onClick={regenerate}>
            <RefreshCw /> {retry ? "Opnieuw proberen" : "Opnieuw genereren"}
          </Button>
          <Button size="sm" disabled={loading || !result} onClick={() => void copyPrompt()}>
            {copied ? <Check /> : <Copy />} {copied ? "Gekopieerd" : "Kopieer"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
