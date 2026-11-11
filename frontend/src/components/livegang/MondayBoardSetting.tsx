"use client"

import { ExternalLink, Loader2 } from "lucide-react"
import { useCallback, useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  createMondayBoard,
  fetchMondaySettings,
  linkMondayBoard,
  MONDAY_CHANGED_EVENT,
  type MondaySettings,
} from "@/lib/launch-checklist"

/** Monday-bord van de klant: tonen, aanmaken in de map, of een bestaand bord koppelen. */
export function MondayBoardSetting({ customerId }: { customerId: string }) {
  const [settings, setSettings] = useState<MondaySettings | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [linking, setLinking] = useState(false)
  const [boardInput, setBoardInput] = useState("")

  const load = useCallback(async () => {
    try {
      setSettings(await fetchMondaySettings(customerId))
    } catch (err) {
      setError((err as Error).message)
    }
  }, [customerId])

  useEffect(() => {
    void load()
    // Bij de eerste keer doorzetten maakt de backend het bord aan: dan verversen.
    const onChanged = () => void load()
    window.addEventListener(MONDAY_CHANGED_EVENT, onChanged)
    return () => window.removeEventListener(MONDAY_CHANGED_EVENT, onChanged)
  }, [load])

  async function run(action: () => Promise<MondaySettings>) {
    setBusy(true)
    setError(null)
    try {
      setSettings(await action())
      setLinking(false)
      setBoardInput("")
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  if (!settings) {
    return error ? <p className="text-sm text-red-700">Monday: {error}</p> : null
  }

  const hasBoard = Boolean(settings.board_id)

  return (
    <section className="space-y-2 rounded-lg border bg-card px-4 py-3 text-sm">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <span className="font-medium">Monday-bord</span>
        {!settings.token_configured ? (
          <span className="text-muted-foreground">
            Niet gekoppeld: zet MONDAY_API_TOKEN in de backend-configuratie.
          </span>
        ) : hasBoard ? (
          <>
            {settings.board_url ? (
              <a
                href={settings.board_url}
                target="_blank"
                rel="noreferrer noopener"
                className="inline-flex items-center gap-1 text-primary hover:underline"
              >
                {settings.board_name ?? `Bord ${settings.board_id}`}
                <ExternalLink className="size-3.5" />
              </a>
            ) : (
              <span>{settings.board_name ?? `Bord ${settings.board_id}`}</span>
            )}
            <Button
              size="sm"
              variant="ghost"
              className="ml-auto"
              disabled={busy}
              onClick={() => {
                if (window.confirm("Bord ontkoppelen? Het bord en de items in Monday blijven bestaan.")) {
                  void run(() => linkMondayBoard(customerId, null))
                }
              }}
            >
              Ontkoppelen
            </Button>
          </>
        ) : (
          <>
            <span className="text-muted-foreground">
              Nog geen bord. Het wordt aangemaakt in de map “{settings.folder_name}” zodra je punten doorzet.
            </span>
            <div className="ml-auto flex flex-wrap gap-2">
              <Button size="sm" variant="outline" disabled={busy} onClick={() => void run(() => createMondayBoard(customerId))}>
                {busy && !linking ? <Loader2 className="animate-spin" /> : null} Bord nu aanmaken
              </Button>
              <Button size="sm" variant="ghost" disabled={busy} onClick={() => setLinking((v) => !v)}>
                Bestaand bord koppelen
              </Button>
            </div>
          </>
        )}
      </div>

      {linking && !hasBoard && (
        <form
          className="flex flex-wrap items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            if (boardInput.trim()) void run(() => linkMondayBoard(customerId, boardInput.trim()))
          }}
        >
          <Input
            value={boardInput}
            onChange={(e) => setBoardInput(e.target.value)}
            placeholder="Bord-id of bord-URL uit Monday"
            className="h-8 max-w-md"
          />
          <Button size="sm" type="submit" disabled={busy || !boardInput.trim()}>
            Koppelen
          </Button>
        </form>
      )}

      {settings.board_error && <p className="text-red-700">{settings.board_error}</p>}
      {error && <p className="text-red-700">{error}</p>}
    </section>
  )
}
