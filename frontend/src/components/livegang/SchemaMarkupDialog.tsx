"use client"

import { AlertTriangle, Check, CheckCircle2, Copy, Loader2, RefreshCw } from "lucide-react"
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
import { Pill } from "@/components/livegang/shared"
import {
  createSchemaMarkup,
  formatDateTime,
  type LaunchScanPage,
  type SchemaMarkupResponse,
} from "@/lib/launch-checklist"

/**
 * JSON-LD-schema voor één pagina, als kant-en-klaar `<script>`-blok om op de klantsite te plakken.
 * Bij openen vraagt de dialog het blok op: de backend geeft de opgeslagen versie direct terug, of maakt
 * er synchroon een (kan tientallen seconden duren). Mount per pagina (met `key`), zodat elke opening
 * met een schone staat begint.
 */
export function SchemaMarkupDialog({
  scanId,
  page,
  onClose,
  onGenerated,
}: {
  scanId: string
  page: LaunchScanPage
  onClose: () => void
  /** Na een geslaagde aanroep met een blok: zodat de lijst zonder herladen toont dat er schema is. */
  onGenerated: (pageId: string, generatedAt: string) => void
}) {
  const [result, setResult] = useState<SchemaMarkupResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  // Alleen het antwoord op de laatste aanvraag telt.
  const requestRef = useRef(0)
  // Eén aanvraag bij openen, ook als React (StrictMode) het effect dubbel draait: anders twee modelaanroepen.
  const startedRef = useRef(false)

  function request(regenerate: boolean) {
    const id = ++requestRef.current
    return createSchemaMarkup(scanId, page.id, regenerate).then(
      (next) => {
        // Ook na sluiten doorgeven, zodat het icoon in de lijst klopt. Niets ontbrekend = niets opgeslagen.
        if (!next.nothing_missing) onGenerated(page.id, next.generated_at)
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
    // Alleen bij openen; de dialog wordt per pagina opnieuw gemount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Zonder resultaat (eerste aanvraag mislukt) is het een nieuwe poging; anders echt opnieuw genereren.
  const retry = !result && error !== null
  function regenerate() {
    setLoading(true)
    setError(null)
    setCopied(false)
    void request(!retry)
  }

  const hasScript = !!result && !result.nothing_missing && !!result.script

  async function copyScript() {
    if (!result || !hasScript) return
    try {
      await navigator.clipboard.writeText(result.script)
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
          <DialogTitle>Schema markup</DialogTitle>
          <DialogDescription className="break-all">{page.path || page.url}</DialogDescription>
        </DialogHeader>

        {loading && (
          <div className="flex items-center gap-2 rounded-md border bg-muted/30 px-3 py-6 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" />
            {result ? "Nieuw schema maken… dit kan even duren." : "Schema ophalen of maken… dit kan even duren."}
          </div>
        )}

        {!loading && result?.nothing_missing && (
          <div className="flex items-start gap-2 rounded-md border border-green-300 bg-green-50 px-3 py-3 text-sm text-green-900 dark:border-green-800 dark:bg-green-950/40 dark:text-green-200">
            <CheckCircle2 className="mt-0.5 size-4 shrink-0" />
            <p>
              {result.notes || "Het verwachte schema voor dit paginatype staat al op de pagina."} Er is niets gemaakt
              en er hoeft niets geplakt te worden.
            </p>
          </div>
        )}

        {!loading && result && !result.nothing_missing && (
          <div className="min-w-0 space-y-3">
            {result.placeholders.length > 0 && (
              <div className="space-y-1 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
                <p className="font-medium">Eerst invullen</p>
                <p className="text-xs">Vervang deze plaatshouders in het blok voordat je het plakt:</p>
                <ul className="list-disc space-y-0.5 pl-5 font-mono text-xs">
                  {result.placeholders.map((p) => (
                    <li key={p} className="break-all">{p}</li>
                  ))}
                </ul>
              </div>
            )}

            {result.problems.length > 0 && (
              <div className="space-y-1 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-900 dark:border-red-800 dark:bg-red-950/40 dark:text-red-200">
                <p className="flex items-center gap-1.5 font-medium">
                  <AlertTriangle className="size-4 shrink-0" /> Controleer vóór plaatsen
                </p>
                <ul className="list-disc space-y-0.5 pl-5 text-xs">
                  {result.problems.map((p, i) => (
                    <li key={i}>{p}</li>
                  ))}
                </ul>
              </div>
            )}

            {result.types.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {result.types.map((t) => (
                  <Pill key={t} tone="blue">{t}</Pill>
                ))}
              </div>
            )}

            <pre className="max-h-[50vh] overflow-auto whitespace-pre-wrap break-words rounded-md border bg-muted/30 p-3 font-mono text-xs">
              {result.script}
            </pre>

            {result.notes && <p className="text-xs text-muted-foreground">{result.notes}</p>}

            <p className="text-xs text-muted-foreground">
              Plaatsen: met Rank Math via het Schema-tabblad van de pagina (aangepast schema importeren); anders in een
              HTML-widget onderaan de pagina in Elementor.
            </p>
          </div>
        )}

        {error && <p className="text-sm text-red-600">{error}</p>}

        <DialogFooter className="sm:items-center">
          {result && !loading && (
            <p className="text-xs text-muted-foreground sm:mr-auto">
              {result.nothing_missing ? "Gecontroleerd" : result.cached ? "Opgeslagen versie" : "Nieuw gemaakt"} ·{" "}
              {formatDateTime(result.generated_at)}
            </p>
          )}
          <Button size="sm" variant="outline" disabled={loading} onClick={regenerate}>
            <RefreshCw /> {retry ? "Opnieuw proberen" : "Opnieuw genereren"}
          </Button>
          <Button size="sm" disabled={loading || !hasScript} onClick={() => void copyScript()}>
            {copied ? <Check /> : <Copy />} {copied ? "Gekopieerd" : "Kopieer"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
