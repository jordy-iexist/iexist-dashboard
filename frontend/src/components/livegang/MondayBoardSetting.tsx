"use client"

import { ExternalLink, KanbanSquare, Loader2 } from "lucide-react"
import { useCallback, useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Pill } from "@/components/livegang/shared"
import {
  createMondayBoard,
  fetchMondaySettings,
  linkMondayBoard,
  MONDAY_CHANGED_EVENT,
  type MondaySettings,
} from "@/lib/launch-checklist"

/**
 * Monday-bord van de klant: tonen, aanmaken in de map, of een bestaand bord koppelen.
 * Wordt als strook onderin de fasekaart getoond.
 */
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

  const label = (
    <span className="flex items-center gap-2 font-medium">
      <KanbanSquare className="size-4 text-muted-foreground" />
      Monday
    </span>
  )

  if (!settings) {
    return (
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-t bg-muted/30 px-4 py-3 text-sm sm:px-5">
        {label}
        {error ? (
          <span className="text-red-700 dark:text-red-400">{error}</span>
        ) : (
          <span className="inline-flex items-center gap-1.5 text-muted-foreground">
            <Loader2 className="size-3.5 animate-spin" /> Status laden…
          </span>
        )}
      </div>
    )
  }

  const hasBoard = Boolean(settings.board_id)
  const boardName = settings.board_name ?? `Bord ${settings.board_id}`

  return (
    <div className="space-y-3 border-t bg-muted/30 px-4 py-3 text-sm sm:px-5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        {label}
        {!settings.token_configured ? (
          <>
            <Pill>Niet geconfigureerd</Pill>
            <span className="text-muted-foreground">Zet MONDAY_API_TOKEN in de backend-configuratie.</span>
          </>
        ) : hasBoard ? (
          <>
            <Pill tone="green">Gekoppeld</Pill>
            {settings.board_url ? (
              <a
                href={settings.board_url}
                target="_blank"
                rel="noreferrer noopener"
                className="inline-flex min-w-0 items-center gap-1 font-medium text-primary hover:underline"
              >
                <span className="truncate">{boardName}</span>
                <ExternalLink className="size-3.5 shrink-0" />
              </a>
            ) : (
              <span className="font-medium">{boardName}</span>
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
              {busy ? <Loader2 className="animate-spin" /> : null} Ontkoppelen
            </Button>
          </>
        ) : (
          <>
            <Pill tone="amber">Nog geen bord</Pill>
            <span className="text-muted-foreground">
              Wordt aangemaakt in map “{settings.folder_name}” zodra je punten doorzet.
            </span>
            <div className="ml-auto flex flex-wrap gap-2">
              <Button size="sm" variant="outline" disabled={busy} onClick={() => void run(() => createMondayBoard(customerId))}>
                {busy && !linking ? <Loader2 className="animate-spin" /> : null} Bord nu aanmaken
              </Button>
              <Button size="sm" variant={linking ? "secondary" : "ghost"} disabled={busy} onClick={() => setLinking((v) => !v)}>
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
            className="h-8 max-w-md bg-background"
            autoFocus
          />
          <Button size="sm" type="submit" disabled={busy || !boardInput.trim()}>
            {busy ? <Loader2 className="animate-spin" /> : null} Koppelen
          </Button>
          <Button size="sm" type="button" variant="ghost" disabled={busy} onClick={() => setLinking(false)}>
            Annuleren
          </Button>
        </form>
      )}

      {(settings.board_error || error) && (
        <div className="space-y-1 rounded-md border border-red-300 bg-background px-3 py-2 text-red-700 dark:text-red-400">
          {settings.board_error && <p>{settings.board_error}</p>}
          {error && <p>{error}</p>}
        </div>
      )}
    </div>
  )
}
