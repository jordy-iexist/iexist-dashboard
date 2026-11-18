"use client"

import { AlertTriangle, Check, CheckCircle2, Copy, Loader2, RefreshCw, Trash2, Upload } from "lucide-react"
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
import {
  ReplacedDefaultTypes,
  SchemaEntities,
  SchemaOmitted,
  SchemaPlaceholders,
  SchemaProblems,
  SchemaScriptView,
  SchemaStaleNotice,
  SchemaTargetInfo,
} from "@/components/livegang/SchemaMarkupParts"
import {
  createSchemaMarkup,
  formatDateTime,
  placeSchemaMarkup,
  removeSchemaMarkup,
  type LaunchScanPage,
  type SchemaMarkupResponse,
} from "@/lib/launch-checklist"
import { cn } from "@/lib/utils"

type PlacementAction = "place" | "remove"

const pageLinkClass = "break-all font-medium underline underline-offset-2 hover:no-underline"

/**
 * JSON-LD-schema voor één pagina, als kant-en-klaar `<script>`-blok om op de klantsite te plakken, of om
 * via Rank Math direct op de live pagina te zetten (en daar weer te verwijderen; beide na bevestiging).
 * Bij openen vraagt de dialog het blok op: de backend geeft de opgeslagen versie direct terug, of maakt
 * er synchroon een (kan tientallen seconden duren). Mount per pagina (met `key`), zodat elke opening
 * met een schone staat begint.
 */
export function SchemaMarkupDialog({
  scanId,
  page,
  onClose,
  onGenerated,
  onPlacementChange,
  onResult,
}: {
  scanId: string
  page: LaunchScanPage
  onClose: () => void
  /** Na elk geslaagd antwoord het volledige resultaat (o.a. voor de beoordeling in de lijst). */
  onResult?: (pageId: string, result: SchemaMarkupResponse) => void
  /** Na een geslaagde aanroep met een blok: zodat de lijst zonder herladen toont dat er schema is. */
  onGenerated: (pageId: string, generatedAt: string) => void
  /** Na elk antwoord: zodat de lijst zonder herladen toont of het schema op de site staat. */
  onPlacementChange: (pageId: string, placedAt: string | null) => void
}) {
  const [result, setResult] = useState<SchemaMarkupResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  // Plaatsen/verwijderen gaat pas na een bevestiging in de dialog: het raakt de live klantsite.
  const [confirm, setConfirm] = useState<PlacementAction | null>(null)
  const [busy, setBusy] = useState<PlacementAction | null>(null)
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
        onPlacementChange(page.id, next.placement?.placed_at ?? null)
        onResult?.(page.id, next)
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
    setConfirm(null)
    void request(!retry)
  }

  function runPlacement(action: PlacementAction) {
    const id = ++requestRef.current
    setBusy(action)
    setError(null)
    const call = action === "place" ? placeSchemaMarkup : removeSchemaMarkup
    call(scanId, page.id).then(
      (next) => {
        // Ook na sluiten doorgeven, zodat het icoon in de lijst klopt.
        onPlacementChange(page.id, next.placement?.placed_at ?? null)
        onResult?.(page.id, next)
        if (id !== requestRef.current) return
        setResult(next)
        setConfirm(null)
        setBusy(null)
      },
      (err: unknown) => {
        if (id !== requestRef.current) return
        setError((err as Error).message)
        setConfirm(null)
        setBusy(null)
      }
    )
  }

  function askConfirm(action: PlacementAction) {
    setError(null)
    setConfirm(action)
  }

  const hasScript = !!result && !result.nothing_missing && !!result.script
  const placement = result?.placement ?? null
  const canPlace = hasScript && !!result?.can_place
  const blockedReason = hasScript && !result?.can_place ? (result?.place_blocked_reason ?? "").trim() : ""
  const replacesDefaults = result?.replaces_default_types ?? []
  // Nog niet geplaatst, of het voorstel is daarna opnieuw gegenereerd: plaatsen is dan de hoofdactie.
  const placePrimary = canPlace && (!placement || !placement.current)
  const working = loading || busy !== null
  const footerDisabled = working || confirm !== null
  const placementOk = !!placement && placement.verified && placement.current

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

  const pageLink = (
    <a href={page.url} target="_blank" rel="noreferrer noopener" className={pageLinkClass}>
      {page.url}
    </a>
  )

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      {/* Nooit hoger dan het scherm: kop, bevestiging en knoppen blijven staan, het middendeel scrolt. */}
      <DialogContent className="flex max-h-[92dvh] flex-col sm:max-w-3xl">
        <DialogHeader className="shrink-0 pr-6">
          <DialogTitle>Schema markup</DialogTitle>
          <DialogDescription className="break-all">{page.path || page.url}</DialogDescription>
        </DialogHeader>

        <div className="-mr-3 min-h-0 flex-1 space-y-4 overflow-y-auto pr-3">
        {loading && (
          <div className="flex items-center gap-2 rounded-md border bg-muted/30 px-3 py-6 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" />
            {result ? "Nieuw schema maken… dit kan even duren." : "Schema ophalen of maken… dit kan even duren."}
          </div>
        )}

        {!loading && placement && (
          <div
            className={cn(
              "space-y-1 rounded-md border px-3 py-2 text-sm",
              placementOk
                ? "border-green-300 bg-green-50 text-green-900 dark:border-green-800 dark:bg-green-950/40 dark:text-green-200"
                : "border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200"
            )}
          >
            <p className="flex items-center gap-1.5 font-medium">
              {placementOk ? <CheckCircle2 className="size-4 shrink-0" /> : <AlertTriangle className="size-4 shrink-0" />}
              Geplaatst in Rank Math op {formatDateTime(placement.placed_at)}
              {placement.site_name ? ` (${placement.site_name})` : ""}
            </p>
            {placement.verified ? (
              <p className="text-xs">Zichtbaar op de pagina.</p>
            ) : (
              <p className="text-xs">
                Nog niet teruggevonden op de pagina, mogelijk door caching;{" "}
                <a href={page.url} target="_blank" rel="noreferrer noopener" className={pageLinkClass}>
                  controleer de pagina
                </a>
                .
              </p>
            )}
            {!placement.current && (
              <p className="text-xs">
                Het voorstel is na het plaatsen opnieuw gegenereerd; op de site staat nog de vorige versie. Plaats
                opnieuw om de site bij te werken.
              </p>
            )}
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
            <SchemaStaleNotice stale={result.stale} />

            <SchemaPlaceholders placeholders={result.placeholders} />

            <SchemaProblems problems={result.problems} />

            <SchemaTargetInfo result={result} />

            <SchemaEntities result={result} />

            <SchemaScriptView result={result} preClassName="max-h-[45dvh]" />

            <SchemaOmitted omitted={result.omitted} />

            {result.notes && <p className="text-xs text-muted-foreground">{result.notes}</p>}

            <p className="text-xs text-muted-foreground">
              Plaatsen: met Rank Math via het Schema-tabblad van de pagina (aangepast schema importeren); anders in een
              HTML-widget onderaan de pagina in Elementor.
            </p>
          </div>
        )}

        {!loading && blockedReason && (
          <p className="text-xs text-muted-foreground">{blockedReason}</p>
        )}
        </div>

        {!loading && confirm && (
          <div className="shrink-0 space-y-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
            {confirm === "place" ? (
              <>
                <p className="font-medium">Schema op de live site zetten?</p>
                <p className="text-xs">
                  Dit schema komt via Rank Math direct op de live pagina {pageLink}
                  {placement ? "; het eerder geplaatste schema wordt vervangen." : "."}
                </p>
                {replacesDefaults.length > 0 && (
                  <div className="space-y-1">
                    <p className="text-xs">Het standaardschema van Rank Math voor deze pagina vervalt:</p>
                    <ReplacedDefaultTypes types={replacesDefaults} />
                  </div>
                )}
              </>
            ) : (
              <>
                <p className="font-medium">Schema van de live site verwijderen?</p>
                <p className="text-xs">
                  Het geplaatste schema wordt uit Rank Math op de live pagina {pageLink} verwijderd.
                </p>
              </>
            )}
            <div className="flex flex-wrap justify-end gap-2 pt-1">
              <Button size="sm" variant="outline" disabled={busy !== null} onClick={() => setConfirm(null)}>
                Annuleren
              </Button>
              <Button
                size="sm"
                variant={confirm === "remove" ? "destructive" : "default"}
                disabled={busy !== null}
                onClick={() => runPlacement(confirm)}
              >
                {busy ? <Loader2 className="animate-spin" /> : confirm === "remove" ? <Trash2 /> : <Upload />}
                {confirm === "remove" ? (busy ? "Verwijderen…" : "Verwijderen") : busy ? "Plaatsen…" : "Plaatsen"}
              </Button>
            </div>
          </div>
        )}

        {error && <p className="shrink-0 text-sm text-red-600">{error}</p>}

        <DialogFooter className="shrink-0 sm:flex-wrap sm:items-center">
          {result && !loading && (
            <p className="text-xs text-muted-foreground sm:mr-auto">
              {result.nothing_missing ? "Gecontroleerd" : result.cached ? "Opgeslagen versie" : "Nieuw gemaakt"} ·{" "}
              {formatDateTime(result.generated_at)}
            </p>
          )}
          <Button size="sm" variant="outline" disabled={footerDisabled} onClick={regenerate}>
            <RefreshCw /> {retry ? "Opnieuw proberen" : "Opnieuw genereren"}
          </Button>
          {placement && !loading && (
            <Button
              size="sm"
              variant="ghost"
              className="text-red-700 hover:text-red-800 dark:text-red-400"
              disabled={footerDisabled}
              onClick={() => askConfirm("remove")}
            >
              <Trash2 /> Verwijder van site
            </Button>
          )}
          {hasScript && !loading && (
            <Button
              size="sm"
              variant={placePrimary ? "default" : "outline"}
              disabled={footerDisabled || !canPlace}
              onClick={() => askConfirm("place")}
            >
              <Upload /> {placement ? "Opnieuw plaatsen" : "Plaats in Rank Math"}
            </Button>
          )}
          <Button
            size="sm"
            variant={placePrimary ? "outline" : "default"}
            disabled={working || !hasScript}
            onClick={() => void copyScript()}
            title="Kopieert het nieuwe blok: dat is wat op de site komt"
          >
            {copied ? <Check /> : <Copy />} {copied ? "Gekopieerd" : "Kopieer"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
