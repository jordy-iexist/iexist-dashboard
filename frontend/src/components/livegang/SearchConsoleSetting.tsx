"use client"

import { Loader2, RefreshCw, Search } from "lucide-react"
import { useCallback, useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { Pill } from "@/components/livegang/shared"
import {
  fetchSearchConsoleSettings,
  setSearchConsoleProperty,
  type SearchConsoleSettings,
} from "@/lib/launch-checklist"

/**
 * Search Console-property van de klant: tonen welke de fase 4-scan gebruikt
 * (automatisch gevonden op domein of handmatig gekozen) en een andere kiezen.
 */
export function SearchConsoleSetting({ customerId }: { customerId: string }) {
  const [settings, setSettings] = useState<SearchConsoleSettings | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [editing, setEditing] = useState(false)
  const [choice, setChoice] = useState("")

  const load = useCallback(
    async (refresh = false) => {
      try {
        setSettings(await fetchSearchConsoleSettings(customerId, refresh))
        setError(null)
      } catch (err) {
        setError((err as Error).message)
      }
    },
    [customerId]
  )

  useEffect(() => {
    void load()
  }, [load])

  async function run(action: () => Promise<SearchConsoleSettings | void>, closeAfter = false) {
    setBusy(true)
    setError(null)
    try {
      const result = await action()
      if (result) setSettings(result)
      if (closeAfter) setEditing(false)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const label = (
    <span className="flex items-center gap-2 font-medium">
      <Search className="size-4 text-muted-foreground" />
      Search Console
    </span>
  )

  if (!settings) {
    return (
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
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

  const others = settings.properties.map((p) => p.site_url).filter((url) => !settings.candidates.includes(url))
  const manual = settings.property_source === "manual"

  function startEditing() {
    setChoice(settings?.property ?? settings?.candidates[0] ?? "")
    setEditing(true)
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        {label}
        {!settings.configured ? (
          <>
            <Pill>Niet geconfigureerd</Pill>
            <span className="text-muted-foreground">
              Zet GSC_CLIENT_ID, GSC_CLIENT_SECRET en GSC_REFRESH_TOKEN in de backend-configuratie.
            </span>
          </>
        ) : settings.property ? (
          <>
            <Pill tone={settings.error ? "amber" : "green"}>{manual ? "Handmatig gekozen" : "Automatisch gevonden"}</Pill>
            <span className="min-w-0 break-all font-mono text-xs">{settings.property}</span>
          </>
        ) : (
          <>
            <Pill tone="amber">Geen property</Pill>
            <span className="text-muted-foreground">
              {settings.error
                ? "De properties konden niet worden opgehaald."
                : "Geen property gevonden voor dit domein: de scan slaat Search Console over."}
            </span>
          </>
        )}
        {settings.configured && !editing && (
          <div className="ml-auto flex flex-wrap gap-2">
            {settings.error && (
              <Button size="sm" variant="ghost" disabled={busy} onClick={() => void run(() => load(true))}>
                {busy ? <Loader2 className="animate-spin" /> : <RefreshCw />} Opnieuw proberen
              </Button>
            )}
            {manual && (
              <Button
                size="sm"
                variant="ghost"
                disabled={busy}
                onClick={() => void run(() => setSearchConsoleProperty(customerId, null))}
              >
                Automatisch kiezen
              </Button>
            )}
            <Button size="sm" variant="outline" disabled={busy || settings.properties.length === 0} onClick={startEditing}>
              {settings.property ? "Wijzigen" : "Property kiezen"}
            </Button>
          </div>
        )}
      </div>

      {editing && (
        <form
          className="flex flex-wrap items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            if (choice) void run(() => setSearchConsoleProperty(customerId, choice), true)
          }}
        >
          <select
            value={choice}
            onChange={(e) => setChoice(e.target.value)}
            className="h-8 max-w-full rounded-md border bg-background px-2 text-sm sm:max-w-md"
            aria-label="Search Console-property"
            disabled={busy}
          >
            {!choice && <option value="">Kies een property…</option>}
            {settings.candidates.length > 0 && (
              <optgroup label="Past bij dit domein">
                {settings.candidates.map((url) => (
                  <option key={url} value={url}>
                    {url}
                  </option>
                ))}
              </optgroup>
            )}
            {others.length > 0 && (
              <optgroup label="Alle properties">
                {others.map((url) => (
                  <option key={url} value={url}>
                    {url}
                  </option>
                ))}
              </optgroup>
            )}
          </select>
          <Button size="sm" type="submit" disabled={busy || !choice}>
            {busy ? <Loader2 className="animate-spin" /> : null} Opslaan
          </Button>
          <Button size="sm" type="button" variant="ghost" disabled={busy} onClick={() => setEditing(false)}>
            Annuleren
          </Button>
          <Button
            size="sm"
            type="button"
            variant="ghost"
            disabled={busy}
            title="Haal de lijst met properties opnieuw op bij Google"
            onClick={() => void run(() => load(true))}
          >
            <RefreshCw /> Lijst verversen
          </Button>
          <p className="w-full text-xs text-muted-foreground">De keuze geldt vanaf de volgende scan.</p>
        </form>
      )}

      {(settings.error || error) && (
        <div className="space-y-1 rounded-md border border-red-300 bg-background px-3 py-2 text-red-700 dark:text-red-400">
          {settings.error && <p>{settings.error}</p>}
          {error && <p>{error}</p>}
        </div>
      )}
    </div>
  )
}
