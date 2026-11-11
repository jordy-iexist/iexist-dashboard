"use client"

import { ChevronDown, ExternalLink, Loader2, Send } from "lucide-react"
import { useCallback, useEffect, useMemo, useState } from "react"

import { Button } from "@/components/ui/button"
import { Pill, SeverityBadge } from "@/components/livegang/shared"
import {
  apiFetch,
  CATEGORY_LABELS,
  describeMondayPush,
  ISSUE_STATUS_LABELS,
  pushToMonday,
  syncMondayLinks,
  type IssueGroup,
  type IssueStatus,
  type LaunchScanIssue,
} from "@/lib/launch-checklist"
import { cn } from "@/lib/utils"

type IssuesResponse = { issues: LaunchScanIssue[]; total: number; groups: IssueGroup[] }

const STATUS_OPTIONS: IssueStatus[] = ["open", "doorgezet", "opgelost", "genegeerd"]

export function IssuesTab({ scanId, customerId }: { scanId: string; customerId: string }) {
  const [data, setData] = useState<IssuesResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [issueType, setIssueType] = useState<string | null>(null)
  const [category, setCategory] = useState<string>("")
  const [severity, setSeverity] = useState<string>("")
  const [status, setStatus] = useState<string>("open")
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [expanded, setExpanded] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [pushing, setPushing] = useState<string | null>(null)
  const [notice, setNotice] = useState<{ text: string; details: string[]; boardUrl: string | null } | null>(null)

  const load = useCallback(async () => {
    const params = new URLSearchParams({ limit: "2000" })
    if (issueType) params.set("issue_type", issueType)
    if (category) params.set("category", category)
    if (severity) params.set("severity", severity)
    if (status) params.set("status", status)
    try {
      const next = await apiFetch<IssuesResponse>(`/scans/${scanId}/issues?${params}`)
      setData(next)
      // Selectie behouden voor punten die nog in de lijst staan.
      const visible = new Set(next.issues.map((i) => i.id))
      setSelected((prev) => new Set([...prev].filter((id) => visible.has(id))))
      setError(null)
    } catch (err) {
      setError((err as Error).message)
    }
  }, [scanId, issueType, category, severity, status])

  useEffect(() => {
    void load()
  }, [load])

  // In Monday verwijderde items: koppeling opruimen en de lijst verversen.
  useEffect(() => {
    let cancelled = false
    void syncMondayLinks(customerId).then((cleared) => {
      if (!cancelled && cleared > 0) void load()
    })
    return () => {
      cancelled = true
    }
    // Alleen bij openen van de lijst, niet bij elke filterwijziging.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [customerId, scanId])

  const visibleGroups = useMemo(
    () => (data?.groups ?? []).filter((g) => !category || g.category === category),
    [data, category]
  )

  async function updateStatus(ids: string[], next: IssueStatus) {
    if (!ids.length) return
    setBusy(true)
    try {
      await apiFetch("/issues/bulk", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ issue_ids: ids, status: next }),
      })
      await load()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function pushIssues(ids: string[]) {
    if (!ids.length) return
    if (ids.length > 1 && !window.confirm(`${ids.length} actiepunten als items naar Monday doorzetten?`)) return
    setBusy(true)
    setNotice(null)
    setError(null)
    setPushing(`0 / ${ids.length}`)
    try {
      const summary = await pushToMonday({ kind: "issues" }, ids, (done, total) => setPushing(`${done} / ${total}`))
      setNotice({ text: describeMondayPush(summary), details: summary.messages, boardUrl: summary.board_url })
      await load()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setPushing(null)
      setBusy(false)
    }
  }

  const issues = data?.issues ?? []
  // Al doorgezette punten slaat de backend over; hier tellen we wat echt nieuw is.
  const pushable = issues.filter((i) => selected.has(i.id) && !i.external_item_id).map((i) => i.id)
  const allSelected = issues.length > 0 && issues.every((i) => selected.has(i.id))

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[260px_1fr]">
      <aside className="space-y-1">
        <button
          type="button"
          onClick={() => setIssueType(null)}
          className={cn(
            "flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm",
            issueType === null ? "bg-primary/10 font-medium" : "hover:bg-muted"
          )}
        >
          Alle types
          <span className="text-xs text-muted-foreground">{data?.groups.reduce((n, g) => n + g.open, 0) ?? 0} open</span>
        </button>
        {visibleGroups.map((group) => (
          <button
            key={group.issue_type}
            type="button"
            onClick={() => setIssueType(group.issue_type)}
            className={cn(
              "flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm",
              issueType === group.issue_type ? "bg-primary/10 font-medium" : "hover:bg-muted"
            )}
          >
            <span
              className={cn(
                "size-2 shrink-0 rounded-full",
                group.severity === "hoog" ? "bg-red-500" : group.severity === "middel" ? "bg-amber-500" : "bg-muted-foreground/40"
              )}
            />
            <span className="min-w-0 flex-1 truncate">{group.label}</span>
            <span className="text-xs text-muted-foreground">{group.open}/{group.count}</span>
          </button>
        ))}
      </aside>

      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <select value={category} onChange={(e) => setCategory(e.target.value)} className="h-8 rounded-md border bg-background px-2 text-sm">
            <option value="">Alle categorieën</option>
            {Object.entries(CATEGORY_LABELS).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
          <select value={severity} onChange={(e) => setSeverity(e.target.value)} className="h-8 rounded-md border bg-background px-2 text-sm">
            <option value="">Alle ernst</option>
            <option value="hoog">Hoog</option>
            <option value="middel">Middel</option>
            <option value="laag">Laag</option>
          </select>
          <select value={status} onChange={(e) => setStatus(e.target.value)} className="h-8 rounded-md border bg-background px-2 text-sm">
            <option value="">Alle statussen</option>
            {STATUS_OPTIONS.map((s) => (
              <option key={s} value={s}>{ISSUE_STATUS_LABELS[s]}</option>
            ))}
          </select>
          <span className="text-sm text-muted-foreground">{data?.total ?? 0} actiepunten</span>
        </div>

        <div className="flex flex-wrap items-center gap-2 rounded-lg border bg-muted/30 px-3 py-2 text-sm">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={allSelected}
              onChange={() => setSelected(allSelected ? new Set() : new Set(issues.map((i) => i.id)))}
            />
            {selected.size > 0 ? `${selected.size} geselecteerd` : "Selecteer alles"}
          </label>
          <div className="ml-auto flex flex-wrap gap-2">
            {(["opgelost", "genegeerd", "open"] as IssueStatus[]).map((s) => (
              <Button key={s} size="sm" variant="ghost" disabled={busy || selected.size === 0} onClick={() => updateStatus([...selected], s)}>
                Markeer {ISSUE_STATUS_LABELS[s].toLowerCase()}
              </Button>
            ))}
            <Button size="sm" variant="secondary" disabled={busy || pushable.length === 0} onClick={() => void pushIssues(pushable)}>
              {pushing ? <Loader2 className="animate-spin" /> : <Send />}
              {pushing ? `Doorzetten… ${pushing}` : `Doorzetten naar Monday${pushable.length ? ` (${pushable.length})` : ""}`}
            </Button>
          </div>
        </div>

        {error && <p className="text-sm text-red-600">{error}</p>}
        {notice && (
          <div className="rounded-md border bg-muted/30 px-3 py-2 text-sm">
            <p>
              {notice.text}{" "}
              {notice.boardUrl && (
                <a href={notice.boardUrl} target="_blank" rel="noreferrer noopener" className="text-primary hover:underline">
                  Open het bord
                </a>
              )}
            </p>
            {notice.details.map((detail) => (
              <p key={detail} className="text-xs text-red-700">{detail}</p>
            ))}
          </div>
        )}
        {!data && !error && <p className="text-sm text-muted-foreground">Laden…</p>}

        <ul className="divide-y rounded-lg border bg-card">
          {issues.map((issue) => {
            const open = expanded === issue.id
            return (
              <li key={issue.id} className="px-3 py-2">
                <div className="flex items-start gap-3">
                  <input type="checkbox" className="mt-1.5" checked={selected.has(issue.id)} onChange={() => toggle(issue.id)} />
                  <button type="button" onClick={() => setExpanded(open ? null : issue.id)} className="min-w-0 flex-1 text-left">
                    <div className="flex flex-wrap items-center gap-2">
                      <SeverityBadge severity={issue.severity} />
                      <Pill>{CATEGORY_LABELS[issue.category] ?? issue.category}</Pill>
                      <span className="text-sm font-medium">{issue.title}</span>
                      <ChevronDown className={cn("ml-auto size-4 text-muted-foreground transition-transform", open && "rotate-180")} />
                    </div>
                    {issue.url && <p className="truncate text-xs text-muted-foreground">{issue.url}</p>}
                  </button>
                  {issue.external_url ? (
                    <a
                      href={issue.external_url}
                      target="_blank"
                      rel="noreferrer noopener"
                      className="inline-flex h-7 items-center gap-1 text-xs text-primary hover:underline"
                    >
                      Monday <ExternalLink className="size-3" />
                    </a>
                  ) : (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-7 px-2"
                      disabled={busy}
                      title="Doorzetten naar Monday"
                      aria-label="Doorzetten naar Monday"
                      onClick={() => void pushIssues([issue.id])}
                    >
                      <Send />
                    </Button>
                  )}
                  <select
                    value={issue.status}
                    disabled={busy}
                    onChange={(e) => updateStatus([issue.id], e.target.value as IssueStatus)}
                    className="h-7 rounded-md border bg-background px-1.5 text-xs"
                  >
                    {STATUS_OPTIONS.map((s) => (
                      <option key={s} value={s}>{ISSUE_STATUS_LABELS[s]}</option>
                    ))}
                  </select>
                </div>
                {open && (
                  <div className="ml-7 mt-2 space-y-2 text-sm">
                    <p>{issue.description}</p>
                    {issue.recommendation && (
                      <p className="rounded-md bg-primary/5 p-2"><span className="font-medium">Aanpak: </span>{issue.recommendation}</p>
                    )}
                    {issue.details != null && (
                      <pre className="max-h-48 overflow-auto rounded-md bg-muted p-2 text-xs">{JSON.stringify(issue.details, null, 2)}</pre>
                    )}
                  </div>
                )}
              </li>
            )
          })}
          {data && issues.length === 0 && (
            <li className="px-3 py-8 text-center text-sm text-muted-foreground">Geen actiepunten voor deze filters.</li>
          )}
        </ul>
      </div>
    </div>
  )
}
