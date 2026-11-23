"use client"

import { Bot, ChevronDown, ExternalLink, Loader2, Send } from "lucide-react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import { Button } from "@/components/ui/button"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { CheckDetails, DETAIL_ITEM_KEYS } from "@/components/livegang/CheckDetails"
import { FixPromptDialog } from "@/components/livegang/FixPromptDialog"
import { IssueDetails } from "@/components/livegang/IssueDetails"
import { Pill, SeverityBadge } from "@/components/livegang/shared"
import {
  apiFetch,
  CATEGORY_LABELS,
  describeMondayPush,
  formatCount,
  ISSUE_STATUS_LABELS,
  pushToMonday,
  syncMondayLinks,
  valueBoostOf,
  type IssueGroup,
  type IssueSeverity,
  type IssueStatus,
  type LaunchScanIssue,
} from "@/lib/launch-checklist"
import { cn } from "@/lib/utils"

type IssuesResponse = { issues: LaunchScanIssue[]; total: number; groups: IssueGroup[] }

/** Actiepunten van één type uit de (gefilterde) lijst. */
type IssueBucket = {
  issueType: string
  label: string
  category: string
  severity: IssueSeverity
  issues: LaunchScanIssue[]
}

/** Vinkje in schermvolgorde: een losse rij of een hele groep. */
type SelectUnit = { key: string; ids: string[] }

const STATUS_OPTIONS: IssueStatus[] = ["open", "doorgezet", "opgelost", "genegeerd"]
const SEVERITY_RANK: Record<IssueSeverity, number> = { hoog: 0, middel: 1, laag: 2 }

/** Eén sitebreed punt (zonder URL) blijft een losse regel; de rest wordt een groep. */
function isSingle(bucket: IssueBucket): boolean {
  return bucket.issues.length === 1 && !bucket.issues[0].url
}

function pagesLabel(count: number): string {
  return count === 1 ? "1 pagina" : `${count} pagina's`
}

/** Lijst met links/afbeeldingen van een fase-3 actiepunt, of null als we die niet als lijst tonen. */
function issueDetailData(issue: LaunchScanIssue): unknown {
  if (!DETAIL_ITEM_KEYS.has(issue.issue_type)) return null
  const data = (issue.details as { data?: unknown } | null)?.data
  return data && typeof data === "object" ? data : null
}

type IssueRowProps = {
  issue: LaunchScanIssue
  /** Binnen een groep: URL als hoofdregel, geen categorie, titel in het uitklapblok. */
  grouped?: boolean
  selected: boolean
  open: boolean
  busy: boolean
  /** shift: Shift ingedrukt, dan selecteren we een reeks vanaf het anker. */
  onToggleSelected: (shift: boolean) => void
  onToggleOpen: () => void
  onPrompt: () => void
  onPush: () => void
  onStatus: (status: IssueStatus) => void
}

function IssueRow({
  issue,
  grouped = false,
  selected,
  open,
  busy,
  onToggleSelected,
  onToggleOpen,
  onPrompt,
  onPush,
  onStatus,
}: IssueRowProps) {
  const boost = valueBoostOf(issue.details)
  // Binnen een groep is de URL de hoofdregel; zonder URL vallen we terug op de titel.
  const headline = grouped ? issue.url ?? issue.title : issue.title
  return (
    <li className={cn("py-2 pr-3", grouped ? "pl-10" : "pl-3")}>
      <div className="flex items-start gap-3">
        <input
          type="checkbox"
          className="mt-1.5"
          checked={selected}
          onClick={(e) => onToggleSelected(e.shiftKey)}
          onChange={() => {}}
          // Shift+klik mag geen tekst tussen de rijen selecteren.
          onMouseDown={(e) => {
            if (e.shiftKey) e.preventDefault()
          }}
          aria-label={`${headline} selecteren`}
        />
        <div className="min-w-0 flex-1">
          <button type="button" onClick={onToggleOpen} aria-expanded={open} className="w-full text-left">
            <div className="flex flex-wrap items-center gap-2">
              <SeverityBadge severity={issue.severity} />
              {!grouped && <Pill>{CATEGORY_LABELS[issue.category] ?? issue.category}</Pill>}
              {boost && (
                <Pill tone="blue" className="cursor-help">
                  <span
                    title={
                      boost.from
                        ? `Prioriteit verhoogd (was ${boost.from}): deze pagina heeft verkeer of backlinks volgens Ahrefs.`
                        : "Deze pagina heeft verkeer of backlinks volgens Ahrefs."
                    }
                  >
                    Pagina met waarde · {formatCount(boost.org_traffic ?? 0)} bezoeken · {formatCount(boost.refdomains ?? 0)} domeinen
                  </span>
                </Pill>
              )}
              <span className={cn("text-sm font-medium", grouped && "min-w-0 break-all")}>{headline}</span>
              <ChevronDown className={cn("ml-auto size-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")} />
            </div>
          </button>
          {/* Buiten de uitklapknop: een link mag niet in een button staan. */}
          {issue.url && (
            <a
              href={issue.url}
              target="_blank"
              rel="noreferrer noopener"
              title={`${issue.url} openen in een nieuw tabblad`}
              className="inline-flex max-w-full items-center gap-1 text-xs text-muted-foreground hover:text-primary hover:underline"
            >
              {grouped ? <span>Pagina openen</span> : <span className="truncate">{issue.url}</span>}
              <ExternalLink className="size-3 shrink-0" />
            </a>
          )}
        </div>
        <Button
          size="sm"
          variant="ghost"
          className="h-7 px-2"
          title="Maak prompt"
          aria-label="Maak prompt"
          onClick={onPrompt}
        >
          <Bot className={cn(issue.fix_prompt_at && "text-primary")} />
        </Button>
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
            onClick={onPush}
          >
            <Send />
          </Button>
        )}
        <select
          value={issue.status}
          disabled={busy}
          onChange={(e) => onStatus(e.target.value as IssueStatus)}
          aria-label="Status"
          className="h-7 rounded-md border bg-background px-1.5 text-xs"
        >
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>{ISSUE_STATUS_LABELS[s]}</option>
          ))}
        </select>
      </div>
      {open && (
        <div className="ml-7 mt-2 space-y-2 text-sm">
          {/* De titel kan extra informatie bevatten, bijv. "(72 tekens)". */}
          {grouped && <p className="font-medium">{issue.title}</p>}
          <p>{issue.description}</p>
          {issue.recommendation && (
            <p className="rounded-md bg-primary/5 p-2"><span className="font-medium">Aanpak: </span>{issue.recommendation}</p>
          )}
          {issueDetailData(issue) !== null ? (
            <CheckDetails itemKey={issue.issue_type} details={issueDetailData(issue)} />
          ) : (
            // Fase 4: de omschrijving bevat de bevindingen al; daar tonen we geen details.
            !issue.issue_type.startsWith("c4_") && <IssueDetails details={issue.details} />
          )}
        </div>
      )}
    </li>
  )
}

type IssueGroupRowProps = {
  bucket: IssueBucket
  mondayUrl: string | null
  open: boolean
  onOpenChange: (open: boolean) => void
  selectedCount: number
  busy: boolean
  /** shift: Shift ingedrukt, dan selecteren we een reeks vanaf het anker. */
  onToggleSelected: (shift: boolean) => void
  onPush: (ids: string[]) => void
  onStatus: (status: IssueStatus) => void
  children: React.ReactNode
}

function IssueGroupRow({
  bucket,
  mondayUrl,
  open,
  onOpenChange,
  selectedCount,
  busy,
  onToggleSelected,
  onPush,
  onStatus,
  children,
}: IssueGroupRowProps) {
  const checkboxRef = useRef<HTMLInputElement>(null)
  const total = bucket.issues.length
  const allSelected = selectedCount === total
  const someSelected = selectedCount > 0 && !allSelected
  const unpushed = bucket.issues.filter((i) => !i.external_item_id).map((i) => i.id)

  useEffect(() => {
    if (checkboxRef.current) checkboxRef.current.indeterminate = someSelected
  }, [someSelected])

  return (
    <li>
      <Collapsible open={open} onOpenChange={onOpenChange} className="group/issues">
        <div className="flex items-start gap-3 px-3 py-2">
          <input
            ref={checkboxRef}
            type="checkbox"
            className="mt-1.5"
            checked={allSelected}
            onClick={(e) => onToggleSelected(e.shiftKey)}
            onChange={() => {}}
            onMouseDown={(e) => {
              if (e.shiftKey) e.preventDefault()
            }}
            aria-label={`Alle pagina's van ${bucket.label} selecteren`}
          />
          <CollapsibleTrigger className="min-w-0 flex-1 text-left">
            <div className="flex flex-wrap items-center gap-2">
              <SeverityBadge severity={bucket.severity} />
              <Pill>{CATEGORY_LABELS[bucket.category] ?? bucket.category}</Pill>
              <span className="text-sm font-medium">{bucket.label}</span>
              <span className="text-xs text-muted-foreground">{pagesLabel(total)}</span>
            </div>
          </CollapsibleTrigger>
          <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
            {mondayUrl && (
              <a
                href={mondayUrl}
                target="_blank"
                rel="noreferrer noopener"
                title="Hoofditem in Monday openen"
                className="inline-flex h-7 items-center gap-1 text-xs text-primary hover:underline"
              >
                Monday <ExternalLink className="size-3" />
              </a>
            )}
            {unpushed.length > 0 && (
              <Button size="sm" variant="ghost" className="h-7 px-2 text-xs" disabled={busy} onClick={() => onPush(unpushed)}>
                <Send /> Doorzetten naar Monday ({unpushed.length})
              </Button>
            )}
            <select
              value=""
              disabled={busy}
              onChange={(e) => {
                if (e.target.value) onStatus(e.target.value as IssueStatus)
              }}
              aria-label={`Status van alle pagina's van ${bucket.label}`}
              className="h-7 rounded-md border bg-background px-1.5 text-xs"
            >
              <option value="" disabled>Status…</option>
              {STATUS_OPTIONS.map((s) => (
                <option key={s} value={s}>{ISSUE_STATUS_LABELS[s]}</option>
              ))}
            </select>
            <CollapsibleTrigger aria-label={open ? "Pagina's inklappen" : "Pagina's uitklappen"} className="h-7">
              <ChevronDown className="size-4 text-muted-foreground transition-transform group-data-[state=open]/issues:rotate-180" />
            </CollapsibleTrigger>
          </div>
        </div>
        <CollapsibleContent>
          <ul className="divide-y border-t bg-muted/20">{children}</ul>
        </CollapsibleContent>
      </Collapsible>
    </li>
  )
}

export function IssuesTab({ scanId, customerId }: { scanId: string; customerId: string }) {
  const [data, setData] = useState<IssuesResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [issueType, setIssueType] = useState<string | null>(null)
  const [category, setCategory] = useState<string>("")
  const [severity, setSeverity] = useState<string>("")
  const [status, setStatus] = useState<string>("open")
  const [selected, setSelected] = useState<Set<string>>(new Set())
  // Laatst gewoon aangeklikte eenheid; Shift+klik selecteert vanaf hier.
  const [anchor, setAnchor] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [openGroups, setOpenGroups] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)
  const [pushing, setPushing] = useState<string | null>(null)
  const [notice, setNotice] = useState<{ text: string; details: string[]; boardUrl: string | null } | null>(null)
  const [promptIssue, setPromptIssue] = useState<LaunchScanIssue | null>(null)

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

  // Zijbalkgegevens per type (alle punten van de scan), o.a. voor het label en de Monday-link.
  const groupInfo = useMemo(() => new Map((data?.groups ?? []).map((g) => [g.issue_type, g])), [data])

  // De gefilterde lijst per type gegroepeerd: zwaarste ernst eerst, dan het meeste aantal.
  const buckets = useMemo(() => {
    const map = new Map<string, IssueBucket>()
    for (const issue of data?.issues ?? []) {
      let bucket = map.get(issue.issue_type)
      if (!bucket) {
        bucket = {
          issueType: issue.issue_type,
          label: issue.issue_label ?? groupInfo.get(issue.issue_type)?.label ?? issue.issue_type,
          category: issue.category,
          severity: issue.severity,
          issues: [],
        }
        map.set(issue.issue_type, bucket)
      }
      bucket.issues.push(issue)
      if (SEVERITY_RANK[issue.severity] < SEVERITY_RANK[bucket.severity]) bucket.severity = issue.severity
    }
    return [...map.values()].sort(
      (a, b) => SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity] || b.issues.length - a.issues.length
    )
  }, [data, groupInfo])

  // Alle vinkjes in schermvolgorde; rijen van een dichte groep zijn niet zichtbaar.
  const units = useMemo(() => {
    const list: SelectUnit[] = []
    for (const bucket of buckets) {
      if (isSingle(bucket)) {
        list.push({ key: bucket.issues[0].id, ids: [bucket.issues[0].id] })
        continue
      }
      list.push({ key: `group:${bucket.issueType}`, ids: bucket.issues.map((i) => i.id) })
      if (openGroups.has(bucket.issueType)) {
        for (const issue of bucket.issues) list.push({ key: issue.id, ids: [issue.id] })
      }
    }
    return list
  }, [buckets, openGroups])

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

  /** Bevestigingstekst bij doorzetten: per groep, of voor een (gemengde) selectie. */
  function confirmPushText(ids: string[], groupLabel?: string): string {
    if (groupLabel) return `${pagesLabel(ids.length)} doorzetten als subitems onder '${groupLabel}' in Monday?`
    const wanted = new Set(ids)
    const types = buckets.filter((b) => b.issues.some((i) => wanted.has(i.id)))
    if (types.length === 1) {
      return `${ids.length} actiepunten doorzetten als subitems onder '${types[0].label}' in Monday?`
    }
    return (
      `${ids.length} actiepunten (${types.length} types) naar Monday doorzetten? ` +
      "Punten van hetzelfde type komen als subitems onder één hoofditem."
    )
  }

  async function pushIssues(ids: string[], groupLabel?: string) {
    if (!ids.length) return
    if (ids.length > 1 && !window.confirm(confirmPushText(ids, groupLabel))) return
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

  // Na het maken van een prompt het icoon direct bijwerken, zonder de lijst te herladen.
  const markFixPrompt = useCallback((issueId: string, generatedAt: string) => {
    setData((prev) =>
      prev && {
        ...prev,
        issues: prev.issues.map((i) => (i.id === issueId ? { ...i, fix_prompt_at: generatedAt } : i)),
      }
    )
  }, [])

  const issues = data?.issues ?? []
  // Al doorgezette punten slaat de backend over; hier tellen we wat echt nieuw is.
  const pushable = issues.filter((i) => selected.has(i.id) && !i.external_item_id).map((i) => i.id)
  const allSelected = issues.length > 0 && issues.every((i) => selected.has(i.id))

  /**
   * Vinkje aangeklikt. Zonder Shift (of zonder geldig anker) één rij of groep aan/uit en wordt dit het anker.
   * Met Shift krijgt alles tussen anker en klik de nieuwe stand van de aangeklikte eenheid; het anker blijft.
   */
  function handleSelect(key: string, shift: boolean) {
    const target = units.findIndex((u) => u.key === key)
    if (target < 0) return
    const from = shift && anchor ? units.findIndex((u) => u.key === anchor) : -1
    const range = from < 0 ? [units[target]] : units.slice(Math.min(from, target), Math.max(from, target) + 1)
    setSelected((prev) => {
      const next = new Set(prev)
      const deselect = units[target].ids.every((id) => prev.has(id))
      for (const unit of range) {
        for (const id of unit.ids) {
          if (deselect) next.delete(id)
          else next.add(id)
        }
      }
      return next
    })
    if (from < 0) setAnchor(key)
  }

  function setGroupOpen(key: string, open: boolean) {
    setOpenGroups((prev) => {
      const next = new Set(prev)
      if (open) next.add(key)
      else next.delete(key)
      return next
    })
  }

  // In "Alle types" staan groepen dicht; kies je één type, dan staat die groep open.
  function selectIssueType(next: string | null) {
    setIssueType(next)
    setAnchor(null)
    setOpenGroups(next === null ? new Set() : new Set([next]))
  }

  function renderRow(issue: LaunchScanIssue, grouped: boolean) {
    const open = expanded === issue.id
    return (
      <IssueRow
        key={issue.id}
        issue={issue}
        grouped={grouped}
        selected={selected.has(issue.id)}
        open={open}
        busy={busy}
        onToggleSelected={(shift) => handleSelect(issue.id, shift)}
        onToggleOpen={() => setExpanded(open ? null : issue.id)}
        onPrompt={() => setPromptIssue(issue)}
        onPush={() => void pushIssues([issue.id])}
        onStatus={(next) => void updateStatus([issue.id], next)}
      />
    )
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[260px_1fr]">
      <aside className="space-y-1">
        <button
          type="button"
          onClick={() => selectIssueType(null)}
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
            onClick={() => selectIssueType(group.issue_type)}
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
          <select
            value={category}
            onChange={(e) => {
              setCategory(e.target.value)
              setAnchor(null)
            }}
            className="h-8 rounded-md border bg-background px-2 text-sm"
          >
            <option value="">Alle categorieën</option>
            {Object.entries(CATEGORY_LABELS).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
          <select
            value={severity}
            onChange={(e) => {
              setSeverity(e.target.value)
              setAnchor(null)
            }}
            className="h-8 rounded-md border bg-background px-2 text-sm"
          >
            <option value="">Alle ernst</option>
            <option value="hoog">Hoog</option>
            <option value="middel">Middel</option>
            <option value="laag">Laag</option>
          </select>
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value)
              setAnchor(null)
            }}
            className="h-8 rounded-md border bg-background px-2 text-sm"
          >
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
          {selected.size <= 1 && <span className="text-xs text-muted-foreground">Tip: Shift+klik selecteert een reeks</span>}
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
          {buckets.map((bucket) => {
            if (isSingle(bucket)) return renderRow(bucket.issues[0], false)
            const ids = bucket.issues.map((i) => i.id)
            return (
              <IssueGroupRow
                key={bucket.issueType}
                bucket={bucket}
                mondayUrl={groupInfo.get(bucket.issueType)?.monday_url ?? null}
                open={openGroups.has(bucket.issueType)}
                onOpenChange={(open) => setGroupOpen(bucket.issueType, open)}
                selectedCount={ids.filter((id) => selected.has(id)).length}
                busy={busy}
                onToggleSelected={(shift) => handleSelect(`group:${bucket.issueType}`, shift)}
                onPush={(pushIds) => void pushIssues(pushIds, bucket.label)}
                onStatus={(next) => void updateStatus(ids, next)}
              >
                {bucket.issues.map((issue) => renderRow(issue, true))}
              </IssueGroupRow>
            )
          })}
          {data && issues.length === 0 && (
            <li className="px-3 py-8 text-center text-sm text-muted-foreground">Geen actiepunten voor deze filters.</li>
          )}
        </ul>
      </div>
      {promptIssue && (
        <FixPromptDialog
          key={promptIssue.id}
          issue={promptIssue}
          onClose={() => setPromptIssue(null)}
          onGenerated={markFixPrompt}
        />
      )}
    </div>
  )
}
