"use client"

import { useId, useState } from "react"
import { CircleAlert, Loader2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { addManualCompetitor, type CompetitorOverview } from "@/lib/keyword-competitors"

/** Venster "Concurrent toevoegen": één domein; de server controleert en meldt fouten. */
export function AddCompetitorDialog({
  customerId,
  open,
  onOpenChange,
  onAdded,
}: {
  customerId: string
  open: boolean
  onOpenChange: (open: boolean) => void
  onAdded: (overview: CompetitorOverview) => void
}) {
  const inputId = useId()
  const errorId = useId()
  const [domain, setDomain] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function changeOpen(next: boolean) {
    if (busy) return
    if (!next) {
      setDomain("")
      setError(null)
    }
    onOpenChange(next)
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    const value = domain.trim()
    if (!value) {
      setError("Vul een domein in.")
      return
    }
    setBusy(true)
    setError(null)
    try {
      const overview = await addManualCompetitor(customerId, value)
      onAdded(overview)
      setDomain("")
      onOpenChange(false)
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : "Er ging iets mis.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={changeOpen}>
      <DialogContent>
        <form onSubmit={submit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>Concurrent toevoegen</DialogTitle>
            <DialogDescription>
              Het domein komt direct in de lijst en krijgt cijfers zodra je het overzicht bijwerkt met
              &quot;Bijwerken&quot;.
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-1.5">
            <label htmlFor={inputId} className="text-sm font-medium">
              Domein
            </label>
            <Input
              id={inputId}
              value={domain}
              onChange={(event) => setDomain(event.target.value)}
              placeholder="voorbeeld.nl"
              autoComplete="off"
              spellCheck={false}
              autoFocus
              disabled={busy}
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? errorId : undefined}
            />
          </div>

          {error && (
            <p
              id={errorId}
              role="alert"
              className="flex items-start gap-2 rounded-md border border-red-300 px-3 py-2 text-sm text-red-700 dark:text-red-300"
            >
              <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
              <span className="min-w-0">{error}</span>
            </p>
          )}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => changeOpen(false)} disabled={busy}>
              Annuleren
            </Button>
            <Button type="submit" disabled={busy}>
              {busy && <Loader2 className="animate-spin" aria-hidden="true" />}
              Toevoegen
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
