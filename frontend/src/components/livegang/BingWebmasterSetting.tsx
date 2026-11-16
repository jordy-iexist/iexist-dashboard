"use client"

import { Globe, Link2, Loader2, RefreshCw, Unlink } from "lucide-react"
import { useCallback, useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { Pill } from "@/components/livegang/shared"
import {
  bingWebmasterConnectUrl,
  disconnectBingWebmaster,
  fetchBingWebmasterSettings,
  formatDateTime,
  type BingWebmasterSettings,
} from "@/lib/launch-checklist"
import { readUrlParam, writeUrlParams } from "@/lib/url-state"

type Notice = { tone: "ok" | "error"; text: string }

/** Resultaat van de OAuth-callback (`?bing=`); na het lezen halen we het uit de URL. */
function readCallbackNotice(): Notice | null {
  const result = readUrlParam("bing")
  if (!result) return null
  const detail = readUrlParam("bing_melding")
  if (result === "gekoppeld") return { tone: "ok", text: "Bing Webmaster is gekoppeld. De volgende scan haalt de Bing-data op." }
  if (result === "geweigerd") return { tone: "error", text: "De toestemming bij Bing is geweigerd: er is niets gekoppeld." }
  return { tone: "error", text: detail || "De koppeling met Bing is mislukt." }
}

/**
 * Bing Webmaster-koppeling (één voor alle klanten) en of de site van deze klant
 * in het Bing-account staat. Staat hij er niet, dan slaat de scan Bing over en
 * blijft het checklistpunt handmatig.
 */
export function BingWebmasterSetting({ customerId }: { customerId: string }) {
  const [settings, setSettings] = useState<BingWebmasterSettings | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<Notice | null>(readCallbackNotice)

  const load = useCallback(
    async (refresh = false) => {
      try {
        setSettings(await fetchBingWebmasterSettings(customerId, refresh))
        setError(null)
      } catch (err) {
        setError((err as Error).message)
      }
    },
    [customerId]
  )

  useEffect(() => {
    // De melding staat nu in state: een refresh hoeft hem niet opnieuw te tonen.
    writeUrlParams({ bing: null, bing_melding: null })
    void load()
  }, [load])

  async function run(action: () => Promise<unknown>) {
    setBusy(true)
    setError(null)
    try {
      await action()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function disconnect() {
    if (!window.confirm("Bing Webmaster ontkoppelen? Dit geldt voor alle klanten; scans slaan Bing daarna over.")) return
    await run(async () => {
      await disconnectBingWebmaster()
      setNotice(null)
      await load(true)
    })
  }

  const label = (
    <span className="flex items-center gap-2 font-medium">
      <Globe className="size-4 text-muted-foreground" />
      Bing Webmaster
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

  const connectButton = (text: string) => (
    <Button size="sm" variant="outline" asChild>
      {/* Gewone navigatie: de route zet een cookie en stuurt door naar Bing. */}
      <a href={bingWebmasterConnectUrl(customerId)}>
        <Link2 /> {text}
      </a>
    </Button>
  )
  const viaKey = settings.mode === "api_key"

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        {label}
        {!settings.configured ? (
          <>
            <Pill>Niet geconfigureerd</Pill>
            <span className="text-muted-foreground">
              Zet BING_CLIENT_ID, BING_CLIENT_SECRET en BING_WEBMASTER_REDIRECT_URI in de backend-configuratie. Tot die tijd
              voer je de Bing-controle handmatig uit.
            </span>
          </>
        ) : !settings.connected ? (
          <>
            <Pill tone={settings.error ? "red" : "amber"}>{settings.error ? "Koppeling verlopen" : "Niet gekoppeld"}</Pill>
            <span className="text-muted-foreground">
              {settings.error
                ? "Koppel opnieuw, of voer de Bing-controle handmatig uit."
                : "Koppel het Bing-account één keer; dat geldt daarna voor alle klanten."}
            </span>
          </>
        ) : settings.site_state === "linked" ? (
          <>
            <Pill tone="green">{viaKey ? "Gekoppeld via API-key" : "Gekoppeld"}</Pill>
            <span className="min-w-0 break-all font-mono text-xs">{settings.site}</span>
          </>
        ) : settings.site_state === "not_verified" ? (
          <>
            <Pill tone="amber">Site niet geverifieerd</Pill>
            <span className="text-muted-foreground">
              <span className="break-all font-mono text-xs">{settings.site}</span> staat in Bing Webmaster Tools maar is niet
              geverifieerd: verifieer de site daar, of voer de Bing-controle handmatig uit.
            </span>
          </>
        ) : settings.site_state === "not_linked" ? (
          <>
            <Pill tone="amber">Site niet gekoppeld</Pill>
            <span className="text-muted-foreground">
              Deze site staat niet in het Bing-account
              {settings.sites_total != null ? ` (${settings.sites_total} ${settings.sites_total === 1 ? "site" : "sites"})` : ""}:
              voer de Bing-controle handmatig uit, of voeg de site toe in Bing Webmaster Tools.
            </span>
          </>
        ) : (
          <>
            <Pill tone="amber">{viaKey ? "Gekoppeld via API-key" : "Gekoppeld"}</Pill>
            <span className="text-muted-foreground">De sites in het Bing-account konden niet worden opgehaald.</span>
          </>
        )}

        {settings.configured && (
          <div className="ml-auto flex flex-wrap gap-2">
            {settings.connected && (
              <Button
                size="sm"
                variant="ghost"
                disabled={busy}
                title="Haal de lijst met sites opnieuw op bij Bing"
                onClick={() => void run(() => load(true))}
              >
                {busy ? <Loader2 className="animate-spin" /> : <RefreshCw />} Verversen
              </Button>
            )}
            {!viaKey && settings.oauth_available && !settings.connected &&
              connectButton(settings.error ? "Opnieuw koppelen" : "Koppel Bing Webmaster")}
            {!viaKey && settings.connected && (
              <Button size="sm" variant="ghost" disabled={busy} onClick={() => void disconnect()}>
                <Unlink /> Ontkoppelen
              </Button>
            )}
          </div>
        )}
      </div>

      {viaKey && (
        <p className="text-xs text-muted-foreground">
          Lokale testmodus: BING_WEBMASTER_API_KEY is gezet, dus OAuth wordt overgeslagen. In productie koppel je met de knop.
        </p>
      )}
      {settings.connected && !viaKey && settings.connected_at && (
        <p className="text-xs text-muted-foreground">Gekoppeld op {formatDateTime(settings.connected_at)}; geldt voor alle klanten.</p>
      )}

      {notice && (
        <div
          className={
            notice.tone === "ok"
              ? "rounded-md border border-green-300 bg-background px-3 py-2 text-green-800 dark:text-green-300"
              : "rounded-md border border-red-300 bg-background px-3 py-2 text-red-700 dark:text-red-400"
          }
        >
          {notice.text}
        </div>
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
