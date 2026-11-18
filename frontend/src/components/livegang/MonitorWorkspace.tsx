"use client"

import { ExternalLink, Loader2, RefreshCw } from "lucide-react"
import { useCallback, useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { IssuesTab } from "@/components/livegang/IssuesTab"
import { PanelRow, PhasePanel, Pill, PollingFailedNotice, type Tone } from "@/components/livegang/shared"
import { usePolling } from "@/hooks/use-polling"
import { formatDateTime } from "@/lib/launch-checklist"
import {
  fetchSitemapMonitor,
  runSitemapMonitor,
  SITEMAP_CHANGE_LABELS,
  updateSitemapMonitor,
  type SitemapChangeKind,
  type SitemapMonitorStatus,
} from "@/lib/sitemap-monitor"
import { cn } from "@/lib/utils"

const POLL_INTERVAL_MS = 3000
/**
 * Zolang de run niet zichtbaar loopt (wachtrij, sitemap ophalen) wachten we hooguit zo lang
 * op een nieuwe `checked_at`. In een zeldzaam geval slaat de taak de klant over zonder die
 * te verversen; dan stoppen we met wachten in plaats van eindeloos te laden.
 */
const AWAIT_TIMEOUT_MS = 5 * 60 * 1000

const CHANGE_TONES: Record<SitemapChangeKind, Tone> = {
  new: "green",
  changed: "blue",
  removed: "muted",
}

/** "Nu controleren" is aangeklikt: wacht tot `checked_at` afwijkt van `since` en er niets meer loopt. */
type Awaiting = { since: string | null; deadline: number }

export function MonitorWorkspace({ customerId }: { customerId: string }) {
  const [status, setStatus] = useState<SitemapMonitorStatus | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [toggling, setToggling] = useState(false)
  const [starting, setStarting] = useState(false)
  const [awaiting, setAwaiting] = useState<Awaiting | null>(null)
  const [timedOut, setTimedOut] = useState(false)
  // Ophogen na een afgeronde run: de actiepuntenlijst opnieuw laden (via `key`).
  const [issuesVersion, setIssuesVersion] = useState(0)
  const [loadAttempt, setLoadAttempt] = useState(0)

  useEffect(() => {
    let cancelled = false
    fetchSitemapMonitor(customerId)
      .then((data) => {
        if (cancelled) return
        setStatus(data)
        setLoadError(null)
      })
      .catch((err: Error) => {
        if (!cancelled) setLoadError(err.message || "Onbekende fout")
      })
    return () => {
      cancelled = true
    }
  }, [customerId, loadAttempt])

  const tick = useCallback(async () => {
    const next = await fetchSitemapMonitor(customerId)
    setStatus(next)
    if (awaiting) {
      if (next.running) {
        // Er worden pagina's gescand: dat mag langer duren dan de wachttijd.
        setAwaiting({ ...awaiting, deadline: Date.now() + AWAIT_TIMEOUT_MS })
      } else if (next.checked_at !== awaiting.since) {
        setAwaiting(null)
        setIssuesVersion((n) => n + 1)
      } else if (Date.now() > awaiting.deadline) {
        setAwaiting(null)
        setTimedOut(true)
      }
    } else if (!next.running) {
      // Een (dagelijkse) run die al liep toen de pagina openging, is klaar.
      setIssuesVersion((n) => n + 1)
    }
  }, [customerId, awaiting])

  const { failing: pollingFailed } = usePolling(
    tick,
    status !== null && (awaiting !== null || status.running),
    POLL_INTERVAL_MS
  )

  async function toggle() {
    if (!status) return
    setToggling(true)
    setError(null)
    try {
      setStatus(await updateSitemapMonitor(customerId, !status.enabled))
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setToggling(false)
    }
  }

  async function runNow() {
    setStarting(true)
    setError(null)
    setTimedOut(false)
    try {
      const before = await runSitemapMonitor(customerId)
      setStatus(before)
      setAwaiting({ since: before.checked_at, deadline: Date.now() + AWAIT_TIMEOUT_MS })
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setStarting(false)
    }
  }

  if (!status) {
    return (
      <PhasePanel title="Monitor · Dagelijkse sitemapcontrole" description={<MonitorDescription />}>
        {loadError ? (
          <PanelRow tone="error" className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <span className="min-w-0 flex-1">De monitor kon niet worden geladen. ({loadError})</span>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                setLoadError(null)
                setLoadAttempt((n) => n + 1)
              }}
            >
              <RefreshCw /> Opnieuw proberen
            </Button>
          </PanelRow>
        ) : (
          <PanelRow>
            <span className="text-muted-foreground">Monitor laden…</span>
          </PanelRow>
        )}
      </PhasePanel>
    )
  }

  const checking = awaiting !== null || status.running
  const noBaseline = status.total_urls === 0

  return (
    <div className="space-y-4">
      <PhasePanel
        title="Monitor · Dagelijkse sitemapcontrole"
        description={<MonitorDescription />}
        aside={
          status.open_issues > 0 && (
            <Pill tone="amber" className="text-xs">
              {status.open_issues} open actiepunt{status.open_issues === 1 ? "" : "en"}
            </Pill>
          )
        }
      >
        <PanelRow className="space-y-3">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <MonitorSwitch checked={status.enabled} disabled={toggling} onChange={() => void toggle()} />
            <span className="text-muted-foreground">
              Laatst gecontroleerd: {status.checked_at ? formatDateTime(status.checked_at) : "nog nooit"}
              {status.changed_at && ` · laatste wijziging ${formatDateTime(status.changed_at)}`}
              {!noBaseline && ` · ${status.total_urls} URL's in de sitemap`}
            </span>
            <div className="ml-auto">
              <Button
                size="sm"
                onClick={() => void runNow()}
                disabled={starting || checking || !status.has_nulmeting}
                title={status.has_nulmeting ? undefined : "Voer eerst een voltooide nulmeting (fase 1) uit."}
              >
                {starting || checking ? <Loader2 className="animate-spin" /> : <RefreshCw />}
                {checking ? "Controle loopt…" : "Nu controleren"}
              </Button>
            </div>
          </div>
          {checking && (
            <p className="text-muted-foreground">
              {status.running
                ? "Nieuwe en gewijzigde pagina's worden gescand. De actiepunten hieronder worden bijgewerkt zodra dat klaar is."
                : "De controle staat in de wachtrij of haalt de sitemap op…"}
            </p>
          )}
          <PollingFailedNotice failing={pollingFailed} />
        </PanelRow>

        {!status.has_nulmeting && (
          <PanelRow tone="warning">
            Er is nog geen voltooide nulmeting (fase 1). Zonder nulmeting slaat de dagelijkse controle deze klant over en
            kan &quot;Nu controleren&quot; niet worden gestart.
          </PanelRow>
        )}

        {!status.global_enabled && (
          <PanelRow tone="warning">
            De dagelijkse controle staat voor alle klanten uit (noodrem <code>SITEMAP_MONITOR_ENABLED</code>), ook als de
            schakelaar hierboven aan staat. Handmatig controleren met &quot;Nu controleren&quot; kan wel.
          </PanelRow>
        )}

        {status.has_nulmeting && noBaseline && (
          <PanelRow tone="muted">
            Nog geen uitgangssituatie vastgelegd. De eerste controle legt alleen de huidige sitemap vast en scant nog niets;
            vanaf de controle daarna worden nieuwe en gewijzigde pagina&apos;s gescand.
          </PanelRow>
        )}

        {!noBaseline && !status.has_lastmod && (
          <PanelRow tone="warning">
            De sitemap bevat geen <code>lastmod</code>-datums. Gewijzigde pagina&apos;s worden daardoor niet herkend; alleen
            nieuwe en verwijderde pagina&apos;s.
          </PanelRow>
        )}

        {status.last_error && (
          <PanelRow tone="error">Melding bij de laatste controle: {status.last_error}</PanelRow>
        )}

        {timedOut && (
          <PanelRow tone="warning">
            De controle heeft na vijf minuten nog geen resultaat opgeleverd. Mogelijk staat hij nog in de wachtrij of is
            hij overgeslagen omdat er een andere scan liep. Kijk later opnieuw of probeer het nog eens.
          </PanelRow>
        )}

        {error && <PanelRow tone="error">{error}</PanelRow>}
      </PhasePanel>

      <RecentChanges changes={status.recent_changes} />

      {status.scan_id && (
        <section className="space-y-3">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Actiepunten uit de monitor
          </h3>
          <IssuesTab key={`${status.scan_id}:${issuesVersion}`} scanId={status.scan_id} customerId={customerId} />
        </section>
      )}
    </div>
  )
}

function MonitorDescription() {
  return (
    <>
      Vergelijkt elke ochtend de sitemap met de vorige stand. Nieuwe en gewijzigde pagina&apos;s worden gescand en
      leveren actiepunten op; open punten van verwijderde pagina&apos;s worden afgesloten. Gebruikt de nulmeting (fase 1)
      als uitgangspunt.
    </>
  )
}

function MonitorSwitch({ checked, disabled, onChange }: { checked: boolean; disabled: boolean; onChange: () => void }) {
  return (
    <label className="flex items-center gap-2">
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={onChange}
        className={cn(
          "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:opacity-50",
          checked ? "bg-primary" : "bg-muted-foreground/30"
        )}
      >
        <span
          className={cn(
            "inline-block size-4 rounded-full bg-background shadow-xs transition-transform",
            checked ? "translate-x-4.5" : "translate-x-0.5"
          )}
        />
      </button>
      <span className="font-medium">Dagelijkse controle {checked ? "aan" : "uit"}</span>
    </label>
  )
}

function RecentChanges({ changes }: { changes: SitemapMonitorStatus["recent_changes"] }) {
  const counts = changes.reduce(
    (acc, change) => ({ ...acc, [change.kind]: acc[change.kind] + 1 }),
    { new: 0, changed: 0, removed: 0 } as Record<SitemapChangeKind, number>
  )
  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Recente wijzigingen</h3>
        {changes.length > 0 &&
          (Object.keys(counts) as SitemapChangeKind[])
            .filter((kind) => counts[kind] > 0)
            .map((kind) => (
              <Pill key={kind} tone={CHANGE_TONES[kind]}>
                {counts[kind]} {SITEMAP_CHANGE_LABELS[kind].toLowerCase()}
              </Pill>
            ))}
      </div>
      {changes.length === 0 ? (
        <p className="text-sm text-muted-foreground">Nog geen wijzigingen in de sitemap gezien.</p>
      ) : (
        <ul className="max-h-96 divide-y overflow-y-auto rounded-lg border bg-card text-sm">
          {changes.map((change, index) => (
            <li key={`${change.kind}:${change.url}:${change.detected_at}:${index}`} className="flex items-center gap-3 px-4 py-2">
              <Pill tone={CHANGE_TONES[change.kind]} className="w-20 justify-center">
                {SITEMAP_CHANGE_LABELS[change.kind]}
              </Pill>
              <a
                href={change.url}
                target="_blank"
                rel="noreferrer"
                className={cn(
                  "min-w-0 flex-1 truncate hover:underline",
                  change.kind === "removed" && "text-muted-foreground line-through"
                )}
                title={change.url}
              >
                {change.url}
                <ExternalLink className="ml-1 inline size-3 align-baseline opacity-60" />
              </a>
              <span
                className="shrink-0 text-xs text-muted-foreground"
                title={change.lastmod ? `lastmod in de sitemap: ${change.lastmod}` : undefined}
              >
                {formatDateTime(change.detected_at)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
