"use client"

import { useCallback, useEffect, useRef, useState } from "react"

import { RotateCcw } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  AuditCategory,
  AuditIssueItem,
  AuditIssueListResponse,
  AuditItem,
  AuditListResponse,
  AuditPageItem,
  AuditPageListResponse,
  AuditSeverity,
  StartAuditResponse,
} from "@/lib/audit-types"

type Feedback = { type: "error" | "success"; message: string } | null

function getErrorMessage(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== "object") return fallback
  const error = (payload as { error?: unknown }).error
  if (typeof error === "string" && error.trim().length > 0) return error
  return fallback
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "-"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return "-"
  return new Intl.DateTimeFormat("nl-NL", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(date)
}

const ACTIVE_STATUSES = new Set(["pending", "crawling", "scanning"])

const SEVERITY_COLORS: Record<AuditSeverity, string> = {
  critical: "bg-red-100 text-red-800",
  warning: "bg-yellow-100 text-yellow-800",
  info: "bg-blue-100 text-blue-800",
}

const CATEGORY_LABELS: Record<AuditCategory, string> = {
  typography: "Typografie",
  performance: "Performance",
  accessibility: "Toegankelijkheid",
  links: "Links",
  responsive: "Responsief",
  seo: "SEO",
  console_error: "Console",
  functionality: "Functionaliteit",
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    pending: "bg-gray-100 text-gray-700",
    crawling: "bg-blue-100 text-blue-700",
    scanning: "bg-purple-100 text-purple-700",
    completed: "bg-green-100 text-green-700",
    failed: "bg-red-100 text-red-700",
    canceled: "bg-gray-100 text-gray-500",
  }
  const labels: Record<string, string> = {
    pending: "In wachtrij",
    crawling: "Pagina's ontdekken",
    scanning: "Scannen",
    completed: "Voltooid",
    failed: "Mislukt",
    canceled: "Geannuleerd",
  }
  const colorClass = colors[status] ?? "bg-gray-100 text-gray-700"
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${colorClass}`}>
      {labels[status] ?? status}
    </span>
  )
}

function ScoreCircle({ score }: { score: number }) {
  const color =
    score >= 80 ? "text-green-600" : score >= 50 ? "text-yellow-600" : "text-red-600"
  return (
    <div className={`text-3xl font-bold ${color}`}>
      {score}
      <span className="text-sm font-normal text-muted-foreground">/100</span>
    </div>
  )
}

function ProgressBar({ value, max }: { value: number; max: number }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0
  return (
    <div className="w-full bg-muted rounded-full h-2">
      <div
        className="bg-primary h-2 rounded-full transition-all duration-500"
        style={{ width: `${pct}%` }}
      />
    </div>
  )
}

export function WebsiteAuditor() {
  const [url, setUrl] = useState("")
  const [maxPages, setMaxPages] = useState(20)
  const [audits, setAudits] = useState<AuditItem[]>([])
  const [activeAudit, setActiveAudit] = useState<AuditItem | null>(null)
  const [activeTab, setActiveTab] = useState<"overview" | "pages" | "issues">("overview")
  const [pages, setPages] = useState<AuditPageItem[]>([])
  const [issues, setIssues] = useState<AuditIssueItem[]>([])
  const [issueCategory, setIssueCategory] = useState<string>("")
  const [issueSeverity, setIssueSeverity] = useState<string>("")
  const [feedback, setFeedback] = useState<Feedback>(null)
  const [isStarting, setIsStarting] = useState(false)
  const [loadingAudits, setLoadingAudits] = useState(true)
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const showFeedback = (type: "error" | "success", message: string) => {
    setFeedback({ type, message })
    setTimeout(() => setFeedback(null), 5000)
  }

  const fetchAudits = useCallback(async () => {
    try {
      const res = await fetch("/api/audit?limit=20")
      if (!res.ok) return
      const data = (await res.json()) as AuditListResponse | { error: string }
      if ("items" in data) setAudits(data.items)
    } catch {
      // ignore
    }
  }, [])

  const fetchAudit = useCallback(async (auditId: string): Promise<AuditItem | null> => {
    try {
      const res = await fetch(`/api/audit/${auditId}`)
      if (!res.ok) return null
      const data = (await res.json()) as AuditItem | { error: string }
      if ("id" in data) return data
    } catch {
      // ignore
    }
    return null
  }, [])

  const fetchPages = useCallback(async (auditId: string) => {
    try {
      const res = await fetch(`/api/audit/${auditId}/pages?limit=100`)
      if (!res.ok) return
      const data = (await res.json()) as AuditPageListResponse | { error: string }
      if ("pages" in data) setPages(data.pages)
    } catch {
      // ignore
    }
  }, [])

  const fetchIssues = useCallback(
    async (auditId: string, category: string, severity: string) => {
      const params = new URLSearchParams({ limit: "200" })
      if (category) params.set("category", category)
      if (severity) params.set("severity", severity)
      try {
        const res = await fetch(`/api/audit/${auditId}/issues?${params}`)
        if (!res.ok) return
        const data = (await res.json()) as AuditIssueListResponse | { error: string }
        if ("issues" in data) setIssues(data.issues)
      } catch {
        // ignore
      }
    },
    []
  )

  // Initial load
  useEffect(() => {
    fetchAudits().finally(() => setLoadingAudits(false))
  }, [fetchAudits])

  // Polling for active audit
  useEffect(() => {
    if (pollingRef.current) clearInterval(pollingRef.current)
    if (!activeAudit || !ACTIVE_STATUSES.has(activeAudit.status)) return

    pollingRef.current = setInterval(async () => {
      const updated = await fetchAudit(activeAudit.id)
      if (!updated) return
      setActiveAudit(updated)
      setAudits((prev) =>
        prev.map((a) => (a.id === updated.id ? updated : a))
      )
      if (!ACTIVE_STATUSES.has(updated.status)) {
        if (pollingRef.current) clearInterval(pollingRef.current)
        if (updated.status === "completed") {
          fetchPages(updated.id)
          fetchIssues(updated.id, issueCategory, issueSeverity)
        }
      }
    }, 3000)

    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current)
    }
  }, [activeAudit, fetchAudit, fetchIssues, fetchPages, issueCategory, issueSeverity])

  const handleStartAudit = async () => {
    const trimmedUrl = url.trim()
    if (!trimmedUrl) {
      showFeedback("error", "Voer een URL in.")
      return
    }
    setIsStarting(true)
    try {
      const res = await fetch("/api/audit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: trimmedUrl, max_pages: maxPages }),
      })
      const data = (await res.json()) as StartAuditResponse | { error: string }
      if (!res.ok || "error" in data) {
        showFeedback("error", getErrorMessage(data, "Audit starten mislukt."))
        return
      }
      const newAudit = await fetchAudit(data.audit_id)
      if (newAudit) {
        setAudits((prev) => [newAudit, ...prev])
        setActiveAudit(newAudit)
        setPages([])
        setIssues([])
        setActiveTab("overview")
        setUrl("")
      }
    } finally {
      setIsStarting(false)
    }
  }

  const handleSelectAudit = async (audit: AuditItem) => {
    setActiveAudit(audit)
    setActiveTab("overview")
    setPages([])
    setIssues([])
    if (audit.status === "completed") {
      fetchPages(audit.id)
      fetchIssues(audit.id, issueCategory, issueSeverity)
    }
  }

  const handleCancelAudit = async (auditId: string) => {
    try {
      const res = await fetch(`/api/audit/${auditId}/cancel`, { method: "POST" })
      if (!res.ok) {
        const data = await res.json().catch(() => null)
        showFeedback("error", getErrorMessage(data, "Annuleren mislukt."))
        return
      }
      const updated = await fetchAudit(auditId)
      if (updated) {
        setAudits((prev) => prev.map((a) => (a.id === auditId ? updated : a)))
        if (activeAudit?.id === auditId) setActiveAudit(updated)
      }
    } catch {
      showFeedback("error", "Kon niet verbinden met server.")
    }
  }

  const handleDeleteAudit = async (auditId: string) => {
    try {
      const res = await fetch(`/api/audit/${auditId}`, { method: "DELETE" })
      if (!res.ok) {
        const data = await res.json().catch(() => null)
        showFeedback("error", getErrorMessage(data, "Verwijderen mislukt."))
        return
      }
      setAudits((prev) => prev.filter((a) => a.id !== auditId))
      if (activeAudit?.id === auditId) {
        setActiveAudit(null)
        setPages([])
        setIssues([])
      }
    } catch {
      showFeedback("error", "Kon niet verbinden met server.")
    }
  }

  const handleRerunAudit = async (audit: AuditItem) => {
    setIsStarting(true)
    try {
      const res = await fetch("/api/audit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: audit.url, max_pages: audit.max_pages }),
      })
      const data = (await res.json()) as StartAuditResponse | { error: string }
      if (!res.ok || "error" in data) {
        showFeedback("error", getErrorMessage(data, "Audit starten mislukt."))
        return
      }
      const newAudit = await fetchAudit(data.audit_id)
      if (newAudit) {
        setAudits((prev) => [newAudit, ...prev])
        setActiveAudit(newAudit)
        setPages([])
        setIssues([])
        setActiveTab("overview")
      }
    } finally {
      setIsStarting(false)
    }
  }

  const handleTabIssues = async () => {
    setActiveTab("issues")
    if (activeAudit?.status === "completed") {
      fetchIssues(activeAudit.id, issueCategory, issueSeverity)
    }
  }

  const handleTabPages = async () => {
    setActiveTab("pages")
    if (activeAudit?.status === "completed") {
      fetchPages(activeAudit.id)
    }
  }

  const handleFilterIssues = async (cat: string, sev: string) => {
    setIssueCategory(cat)
    setIssueSeverity(sev)
    if (activeAudit?.status === "completed") {
      fetchIssues(activeAudit.id, cat, sev)
    }
  }

  const isRunning = activeAudit ? ACTIVE_STATUSES.has(activeAudit.status) : false

  return (
    <div className="space-y-6">
      {/* Feedback */}
      {feedback && (
        <div
          className={`p-3 rounded text-sm ${
            feedback.type === "error"
              ? "bg-destructive/10 text-destructive"
              : "bg-green-50 text-green-800"
          }`}
        >
          {feedback.message}
        </div>
      )}

      {/* Start audit form */}
      <div className="rounded-lg border p-4 space-y-3">
        <h2 className="font-semibold">Nieuwe audit starten</h2>
        <div className="flex gap-2">
          <Input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://example.com"
            onKeyDown={(e) => e.key === "Enter" && handleStartAudit()}
            className="flex-1"
          />
          <Input
            type="number"
            min={1}
            max={200}
            value={maxPages}
            onChange={(e) => setMaxPages(Number(e.target.value))}
            className="w-24"
            title="Max pagina's"
          />
          <Button onClick={handleStartAudit} disabled={isStarting}>
            {isStarting ? "Starten..." : "Start audit"}
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">
          Voer een volledige URL in (bijv. https://example.com). Max{" "}
          <span className="font-medium">{maxPages}</span> pagina's worden gescand.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Audit list */}
        <div className="space-y-2">
          <h2 className="font-semibold text-sm uppercase tracking-wide text-muted-foreground">
            Eerdere audits
          </h2>
          {loadingAudits ? (
            <p className="text-sm text-muted-foreground">Laden...</p>
          ) : audits.length === 0 ? (
            <p className="text-sm text-muted-foreground">Nog geen audits.</p>
          ) : (
            <div className="space-y-1">
              {audits.map((audit) => (
                <button
                  key={audit.id}
                  onClick={() => handleSelectAudit(audit)}
                  className={`w-full text-left rounded p-2 text-sm border transition-colors ${
                    activeAudit?.id === audit.id
                      ? "border-primary bg-primary/5"
                      : "border-transparent hover:border-muted hover:bg-muted/50"
                  }`}
                >
                  <div className="flex items-center justify-between gap-1">
                    <span className="truncate font-medium">{audit.domain}</span>
                    <StatusBadge status={audit.status} />
                  </div>
                  <div className="text-xs text-muted-foreground mt-0.5">
                    {formatDate(audit.created_at)}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Audit detail */}
        <div className="lg:col-span-2">
          {!activeAudit ? (
            <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground text-sm">
              Selecteer een audit of start een nieuwe.
            </div>
          ) : (
            <div className="space-y-4">
              {/* Header */}
              <div className="rounded-lg border p-4 space-y-3">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <div className="font-semibold break-all">{activeAudit.url}</div>
                    <div className="text-xs text-muted-foreground mt-0.5">
                      {formatDate(activeAudit.created_at)}
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <StatusBadge status={activeAudit.status} />
                    {ACTIVE_STATUSES.has(activeAudit.status) && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => handleCancelAudit(activeAudit.id)}
                      >
                        Annuleren
                      </Button>
                    )}
                    {!ACTIVE_STATUSES.has(activeAudit.status) && (
                      <>
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={isStarting}
                          onClick={() => handleRerunAudit(activeAudit)}
                        >
                          <RotateCcw className="size-4 mr-1" />
                          Opnieuw scannen
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          className="text-destructive hover:text-destructive"
                          onClick={() => handleDeleteAudit(activeAudit.id)}
                        >
                          Verwijderen
                        </Button>
                      </>
                    )}
                  </div>
                </div>

                {/* Progress */}
                {isRunning && (
                  <div className="space-y-1">
                    <div className="flex justify-between text-xs text-muted-foreground">
                      <span>
                        {activeAudit.status === "crawling"
                          ? "Pagina's ontdekken..."
                          : `${activeAudit.scanned_pages} / ${activeAudit.total_pages} pagina's gescand`}
                      </span>
                      <span>
                        {activeAudit.total_pages > 0
                          ? `${Math.round((activeAudit.scanned_pages / activeAudit.total_pages) * 100)}%`
                          : "..."}
                      </span>
                    </div>
                    <ProgressBar
                      value={activeAudit.scanned_pages}
                      max={activeAudit.total_pages || 1}
                    />
                  </div>
                )}

                {/* Stats */}
                {!isRunning && (
                  <div className="grid grid-cols-3 gap-3 text-center text-sm">
                    <div>
                      <div className="font-semibold">{activeAudit.total_pages}</div>
                      <div className="text-xs text-muted-foreground">Pagina's</div>
                    </div>
                    <div>
                      <div className="font-semibold text-red-600">
                        {activeAudit.summary?.critical ?? 0}
                      </div>
                      <div className="text-xs text-muted-foreground">Kritiek</div>
                    </div>
                    <div>
                      {activeAudit.summary ? (
                        <ScoreCircle score={activeAudit.summary.score} />
                      ) : (
                        <div className="font-semibold text-muted-foreground">-</div>
                      )}
                      <div className="text-xs text-muted-foreground">Score</div>
                    </div>
                  </div>
                )}

                {activeAudit.error_message && (
                  <div className="text-xs text-destructive bg-destructive/10 rounded p-2">
                    {activeAudit.error_message}
                  </div>
                )}
              </div>

              {/* Tabs */}
              {activeAudit.status === "completed" && (
                <>
                  <div className="flex gap-1 border-b">
                    {(
                      [
                        { key: "overview", label: "Overzicht" },
                        { key: "pages", label: `Pagina's (${activeAudit.scanned_pages})` },
                        { key: "issues", label: `Issues (${activeAudit.summary?.total_issues ?? 0})` },
                      ] as const
                    ).map((tab) => (
                      <button
                        key={tab.key}
                        onClick={() => {
                          if (tab.key === "issues") handleTabIssues()
                          else if (tab.key === "pages") handleTabPages()
                          else setActiveTab("overview")
                        }}
                        className={`px-3 py-2 text-sm font-medium border-b-2 transition-colors ${
                          activeTab === tab.key
                            ? "border-primary text-primary"
                            : "border-transparent text-muted-foreground hover:text-foreground"
                        }`}
                      >
                        {tab.label}
                      </button>
                    ))}
                  </div>

                  {/* Overview tab */}
                  {activeTab === "overview" && activeAudit.summary && (
                    <div className="space-y-4">
                      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                        <div className="rounded border p-3 text-center">
                          <div className="text-2xl font-bold text-red-600">
                            {activeAudit.summary.critical}
                          </div>
                          <div className="text-xs text-muted-foreground">Kritiek</div>
                        </div>
                        <div className="rounded border p-3 text-center">
                          <div className="text-2xl font-bold text-yellow-600">
                            {activeAudit.summary.warnings}
                          </div>
                          <div className="text-xs text-muted-foreground">Waarschuwingen</div>
                        </div>
                        <div className="rounded border p-3 text-center">
                          <div className="text-2xl font-bold text-blue-600">
                            {activeAudit.summary.info}
                          </div>
                          <div className="text-xs text-muted-foreground">Informatie</div>
                        </div>
                        <div className="rounded border p-3 text-center">
                          <ScoreCircle score={activeAudit.summary.score} />
                          <div className="text-xs text-muted-foreground">Score</div>
                        </div>
                      </div>

                      {/* Issues per category */}
                      {Object.entries(activeAudit.summary.categories).length > 0 && (
                        <div className="space-y-1">
                          <h3 className="text-sm font-medium">Issues per categorie</h3>
                          <div className="space-y-1">
                            {Object.entries(activeAudit.summary.categories)
                              .sort(([, a], [, b]) => b - a)
                              .map(([cat, count]) => (
                                <div key={cat} className="flex items-center gap-2 text-sm">
                                  <span className="w-32 text-muted-foreground">
                                    {CATEGORY_LABELS[cat as AuditCategory] ?? cat}
                                  </span>
                                  <div className="flex-1 bg-muted rounded-full h-1.5">
                                    <div
                                      className="bg-primary h-1.5 rounded-full"
                                      style={{
                                        width: `${Math.min(100, (count / (activeAudit.summary!.total_issues || 1)) * 100)}%`,
                                      }}
                                    />
                                  </div>
                                  <span className="w-6 text-right font-medium">{count}</span>
                                </div>
                              ))}
                          </div>
                        </div>
                      )}

                      {/* Typography summary */}
                      {activeAudit.summary.typography_summary?.unique_font_families &&
                        activeAudit.summary.typography_summary.unique_font_families.length > 0 && (
                          <div className="space-y-1">
                            <h3 className="text-sm font-medium">Gevonden lettertypes</h3>
                            <div className="flex flex-wrap gap-1">
                              {activeAudit.summary.typography_summary.unique_font_families.map(
                                (ff) => (
                                  <span
                                    key={ff}
                                    className="px-2 py-0.5 bg-muted rounded text-xs"
                                  >
                                    {ff}
                                  </span>
                                )
                              )}
                            </div>
                          </div>
                        )}
                    </div>
                  )}

                  {/* Pages tab */}
                  {activeTab === "pages" && (
                    <div className="space-y-2">
                      {pages.length === 0 ? (
                        <p className="text-sm text-muted-foreground">Laden...</p>
                      ) : (
                        pages.map((page) => (
                          <div key={page.id} className="rounded border p-3 text-sm">
                            <div className="flex items-center justify-between gap-2">
                              <span className="truncate font-mono text-xs">{page.path}</span>
                              <div className="flex items-center gap-2 shrink-0">
                                {page.issue_count > 0 && (
                                  <span className="text-xs bg-orange-100 text-orange-700 px-1.5 py-0.5 rounded">
                                    {page.issue_count} issues
                                  </span>
                                )}
                                <StatusBadge status={page.status} />
                              </div>
                            </div>
                            {page.error_message && (
                              <div className="mt-1 text-xs text-destructive">
                                {page.error_message}
                              </div>
                            )}
                            {page.screenshots && (page.screenshots.desktop || page.screenshots.mobile) && (
                              <div className="mt-2 flex gap-2">
                                {(["desktop", "mobile"] as const).map((vp) => {
                                  const url = page.screenshots![vp]
                                  if (!url) return null
                                  return (
                                    <a
                                      key={vp}
                                      href={url}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      className="block shrink-0"
                                      title={`${vp} screenshot openen`}
                                    >
                                      <img
                                        src={url}
                                        alt={`${vp} screenshot van ${page.path}`}
                                        className="h-16 w-auto rounded border object-top object-cover hover:opacity-80 transition-opacity"
                                      />
                                      <span className="block text-center text-xs text-muted-foreground mt-0.5">
                                        {vp}
                                      </span>
                                    </a>
                                  )
                                })}
                              </div>
                            )}
                          </div>
                        ))
                      )}
                    </div>
                  )}

                  {/* Issues tab */}
                  {activeTab === "issues" && (
                    <div className="space-y-3">
                      {/* Filters */}
                      <div className="flex gap-2 flex-wrap">
                        <select
                          value={issueCategory}
                          onChange={(e) =>
                            handleFilterIssues(e.target.value, issueSeverity)
                          }
                          className="text-sm border rounded px-2 py-1 bg-background"
                        >
                          <option value="">Alle categorieën</option>
                          {(Object.keys(CATEGORY_LABELS) as AuditCategory[]).map((cat) => (
                            <option key={cat} value={cat}>
                              {CATEGORY_LABELS[cat]}
                            </option>
                          ))}
                        </select>
                        <select
                          value={issueSeverity}
                          onChange={(e) =>
                            handleFilterIssues(issueCategory, e.target.value)
                          }
                          className="text-sm border rounded px-2 py-1 bg-background"
                        >
                          <option value="">Alle ernst</option>
                          <option value="critical">Kritiek</option>
                          <option value="warning">Waarschuwing</option>
                          <option value="info">Informatie</option>
                        </select>
                      </div>

                      {issues.length === 0 ? (
                        <p className="text-sm text-muted-foreground">
                          Geen issues gevonden met deze filters.
                        </p>
                      ) : (
                        <div className="space-y-2">
                          {issues.map((issue) => (
                            <div key={issue.id} className="rounded border p-3 text-sm space-y-1">
                              <div className="flex items-start gap-2">
                                <span
                                  className={`shrink-0 px-1.5 py-0.5 rounded text-xs font-medium ${SEVERITY_COLORS[issue.severity]}`}
                                >
                                  {issue.severity}
                                </span>
                                <span
                                  className="shrink-0 px-1.5 py-0.5 rounded text-xs bg-muted text-muted-foreground"
                                >
                                  {CATEGORY_LABELS[issue.category] ?? issue.category}
                                </span>
                                <span className="font-medium">{issue.title}</span>
                              </div>
                              {issue.description && (
                                <p className="text-xs text-muted-foreground pl-1">
                                  {issue.description}
                                </p>
                              )}
                              {issue.page_url && (
                                <p className="text-xs text-muted-foreground font-mono pl-1 truncate">
                                  {issue.page_url}
                                </p>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
