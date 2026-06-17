"use client"

import Link from "next/link"
import { useEffect, useMemo, useRef, useState, useTransition } from "react"
import { useRouter } from "next/navigation"
import { Check, Link2, Users } from "lucide-react"

import { Button } from "@/components/ui/button"
import { type BlogsIdsResponse } from "@/lib/blog-types"
import { PublishActionResponse, WordPressSite } from "@/lib/wordpress-types"

type PublishSummary = {
  total: number
  succeeded: number
  failed: number
  pending: number
  processing: number
}

export type BlogListItem = {
  id: string
  shareToken: string
  title: string
  createdDate: string
  filename: string
  words: string
  anchor1: string
  anchor2: string
  preview: string
  publication: PublishSummary
  published_at: string | null
  isPublic: boolean
  isOwner: boolean
  customerName: string | null
}

type SitesResponse =
  | {
      sites: WordPressSite[]
    }
  | {
      error: string
    }

type BatchResponse =
  | PublishActionResponse
  | {
      error: string
    }

function getErrorMessage(payload: unknown, fallback: string) {
  if (!payload || typeof payload !== "object") {
    return fallback
  }
  const error = (payload as { error?: unknown }).error
  if (typeof error === "string" && error.trim().length > 0) {
    return error
  }
  return fallback
}

export type BlogListFilters = {
  scope: string
  customerWebsiteId: string | null
  createdFrom: string | null
  createdTo: string | null
}

type SelectedBlogInfo = {
  shareToken: string
  isOwner: boolean
  isPublic: boolean
}

export function BlogsBatchPublishList({
  blogs,
  totalBlogs,
  filters,
}: {
  blogs: BlogListItem[]
  totalBlogs: number
  filters: BlogListFilters
}) {
  const router = useRouter()
  const [selectedBlogs, setSelectedBlogs] = useState<
    Record<string, SelectedBlogInfo>
  >({})
  const [isSelectingAll, setIsSelectingAll] = useState(false)
  const [selectedSiteIds, setSelectedSiteIds] = useState<string[]>([])
  const [wpStatus, setWpStatus] = useState<"draft" | "publish">("draft")
  const [sites, setSites] = useState<WordPressSite[]>([])
  const [showBatchPanel, setShowBatchPanel] = useState(false)
  const [feedback, setFeedback] = useState<{
    type: "success" | "error" | null
    message: string
  }>({ type: null, message: "" })
  const [copiedShareBlogId, setCopiedShareBlogId] = useState<string | null>(null)
  const [copiedSelection, setCopiedSelection] = useState(false)
  const [isPending, startTransition] = useTransition()
  const pollingIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const copyResetTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const copySelectionResetTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(
    null
  )

  // Stop polling wanneer er geen in-flight publicaties meer zijn
  const hasInFlightPublications = useMemo(
    () =>
      blogs.some(
        (blog) =>
          (blog.publication?.pending ?? 0) > 0 ||
          (blog.publication?.processing ?? 0) > 0
      ),
    [blogs]
  )

  // Start/stop polling op basis van in-flight publicaties
  useEffect(() => {
    if (hasInFlightPublications) {
      if (!pollingIntervalRef.current) {
        pollingIntervalRef.current = setInterval(() => {
          router.refresh()
        }, 8000)
      }
    } else {
      if (pollingIntervalRef.current) {
        clearInterval(pollingIntervalRef.current)
        pollingIntervalRef.current = null
      }
    }
  }, [hasInFlightPublications, router])

  // Ruim polling interval op bij unmount
  useEffect(() => {
    return () => {
      if (pollingIntervalRef.current) {
        clearInterval(pollingIntervalRef.current)
        pollingIntervalRef.current = null
      }
      if (copyResetTimeoutRef.current) {
        clearTimeout(copyResetTimeoutRef.current)
        copyResetTimeoutRef.current = null
      }
      if (copySelectionResetTimeoutRef.current) {
        clearTimeout(copySelectionResetTimeoutRef.current)
        copySelectionResetTimeoutRef.current = null
      }
    }
  }, [])

  // Houd de metadata van geselecteerde blogs (isPublic/isOwner) in sync met verse
  // serverdata na router.refresh(), zodat de deel/ontdeel-keuze niet op een stale
  // snapshot draait.
  useEffect(() => {
    setSelectedBlogs((current) => {
      if (Object.keys(current).length === 0) return current
      let changed = false
      const next = { ...current }
      for (const blog of blogs) {
        const selected = next[blog.id]
        if (
          selected &&
          (selected.isPublic !== blog.isPublic || selected.isOwner !== blog.isOwner)
        ) {
          next[blog.id] = {
            ...selected,
            isPublic: blog.isPublic,
            isOwner: blog.isOwner,
          }
          changed = true
        }
      }
      return changed ? next : current
    })
  }, [blogs])

  const selectedCount = useMemo(
    () => Object.keys(selectedBlogs).length,
    [selectedBlogs]
  )

  const ownedSelectedIds = useMemo(
    () =>
      Object.entries(selectedBlogs)
        .filter(([, info]) => info.isOwner)
        .map(([id]) => id),
    [selectedBlogs]
  )

  const ownedToShare = useMemo(
    () =>
      Object.entries(selectedBlogs)
        .filter(([, info]) => info.isOwner && !info.isPublic)
        .map(([id]) => id),
    [selectedBlogs]
  )

  const ownedToUnshare = useMemo(
    () =>
      Object.entries(selectedBlogs)
        .filter(([, info]) => info.isOwner && info.isPublic)
        .map(([id]) => id),
    [selectedBlogs]
  )

  const sharedSelectedCount = selectedCount - ownedSelectedIds.length

  const allSelected = totalBlogs > 0 && selectedCount >= totalBlogs

  const toggleBlogSelection = (blog: BlogListItem, checked: boolean) => {
    setSelectedBlogs((current) => {
      if (checked) {
        return {
          ...current,
          [blog.id]: { shareToken: blog.shareToken, isOwner: blog.isOwner, isPublic: blog.isPublic },
        }
      }
      const next = { ...current }
      delete next[blog.id]
      return next
    })
  }

  const toggleSelectAll = (checked: boolean) => {
    if (!checked) {
      setSelectedBlogs({})
      return
    }

    setFeedback({ type: null, message: "" })
    setIsSelectingAll(true)
    void (async () => {
      try {
        const params = new URLSearchParams()
        if (filters.scope !== "all") {
          params.set("scope", filters.scope)
        }
        if (filters.customerWebsiteId) {
          params.set("customer_website_id", filters.customerWebsiteId)
        }
        if (filters.createdFrom) {
          params.set("created_from", filters.createdFrom)
        }
        if (filters.createdTo) {
          params.set("created_to", filters.createdTo)
        }
        const query = params.toString()
        const response = await fetch(
          query ? `/api/blogs/ids?${query}` : "/api/blogs/ids",
          { method: "GET", cache: "no-store" }
        )
        const payload = (await response.json().catch(() => null)) as
          | BlogsIdsResponse
          | { error: string }
          | null
        if (!response.ok || !payload || !("blogs" in payload)) {
          throw new Error(getErrorMessage(payload, "Kon selectie niet ophalen."))
        }
        const next: Record<string, SelectedBlogInfo> = {}
        for (const item of payload.blogs) {
          next[item.id] = {
            shareToken: item.share_token,
            isOwner: item.is_owner,
            isPublic: item.is_public ?? false,
          }
        }
        setSelectedBlogs(next)
        if (payload.blogs.length < totalBlogs) {
          setFeedback({
            type: "error",
            message: `Selectie beperkt tot ${payload.blogs.length} van ${totalBlogs} blogs.`,
          })
        }
      } catch (error) {
        setFeedback({
          type: "error",
          message:
            error instanceof Error ? error.message : "Kon selectie niet ophalen.",
        })
      } finally {
        setIsSelectingAll(false)
      }
    })()
  }

  const toggleSiteSelection = (siteId: string, checked: boolean) => {
    setSelectedSiteIds((current) => {
      if (checked) {
        return current.includes(siteId) ? current : [...current, siteId]
      }
      return current.filter((value) => value !== siteId)
    })
  }

  const openBatchPanel = () => {
    setFeedback({ type: null, message: "" })
    setShowBatchPanel(true)

    if (sites.length > 0) {
      return
    }

    startTransition(async () => {
      try {
        const response = await fetch("/api/wordpress/sites", {
          method: "GET",
          cache: "no-store",
        })
        const payload = (await response.json().catch(() => null)) as
          | SitesResponse
          | null
        if (!response.ok) {
          throw new Error(
            getErrorMessage(payload, "Kon WordPress sites niet ophalen.")
          )
        }
        const nextSites =
          payload && "sites" in payload && Array.isArray(payload.sites)
            ? payload.sites.filter((site) => site.is_active)
            : []
        setSites(nextSites)
      } catch (error) {
        setFeedback({
          type: "error",
          message:
            error instanceof Error
              ? error.message
              : "Kon WordPress sites niet ophalen.",
        })
      }
    })
  }

  const copyShareLink = async (blog: BlogListItem) => {
    try {
      await navigator.clipboard.writeText(
        `${window.location.origin}/share/${blog.shareToken}`
      )
      setFeedback({ type: null, message: "" })
      setCopiedShareBlogId(blog.id)
      if (copyResetTimeoutRef.current) {
        clearTimeout(copyResetTimeoutRef.current)
      }
      copyResetTimeoutRef.current = setTimeout(() => {
        setCopiedShareBlogId(null)
        copyResetTimeoutRef.current = null
      }, 1500)
    } catch {
      setFeedback({
        type: "error",
        message: "Kopiëren naar klembord is mislukt.",
      })
    }
  }

  const copySelectionLinks = async () => {
    const links = Object.values(selectedBlogs).map(
      (info) => `${window.location.origin}/share/${info.shareToken}`
    )
    if (links.length === 0) return
    try {
      await navigator.clipboard.writeText(links.join("\n"))
      setFeedback({ type: null, message: "" })
      setCopiedSelection(true)
      if (copySelectionResetTimeoutRef.current) {
        clearTimeout(copySelectionResetTimeoutRef.current)
      }
      copySelectionResetTimeoutRef.current = setTimeout(() => {
        setCopiedSelection(false)
        copySelectionResetTimeoutRef.current = null
      }, 1500)
    } catch {
      setFeedback({
        type: "error",
        message: "Kopiëren naar klembord is mislukt.",
      })
    }
  }

  const deleteBatch = () => {
    if (ownedSelectedIds.length === 0) return
    const confirmed = window.confirm(
      `Weet je zeker dat je ${ownedSelectedIds.length} blog(s) wilt verwijderen? Dit kan niet ongedaan gemaakt worden.`
    )
    if (!confirmed) return

    setFeedback({ type: null, message: "" })
    startTransition(async () => {
      try {
        const response = await fetch("/api/blogs/delete/batch", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ blog_ids: ownedSelectedIds }),
        })
        const payload = (await response.json().catch(() => null)) as
          | { deleted: number; missing: string[]; error?: string }
          | null
        if (!response.ok) {
          throw new Error(getErrorMessage(payload, "Batch verwijderen is mislukt."))
        }
        setFeedback({
          type: "success",
          message: `${payload?.deleted ?? 0} blog(s) verwijderd.`,
        })
        setSelectedBlogs({})
        setShowBatchPanel(false)
        router.refresh()
      } catch (error) {
        setFeedback({
          type: "error",
          message:
            error instanceof Error ? error.message : "Batch verwijderen is mislukt.",
        })
      }
    })
  }

  const shareBatch = () => {
    if (ownedToShare.length === 0 && ownedToUnshare.length === 0) return
    setFeedback({ type: null, message: "" })
    startTransition(async () => {
      try {
        const calls: Promise<Response>[] = []
        if (ownedToShare.length > 0) {
          calls.push(
            fetch("/api/blogs/share/batch", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ blog_ids: ownedToShare, is_public: true }),
            })
          )
        }
        if (ownedToUnshare.length > 0) {
          calls.push(
            fetch("/api/blogs/share/batch", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ blog_ids: ownedToUnshare, is_public: false }),
            })
          )
        }
        const responses = await Promise.all(calls)
        for (const r of responses) {
          if (!r.ok) {
            const payload = await r.json().catch(() => null)
            throw new Error(getErrorMessage(payload, "Deling bijwerken is mislukt."))
          }
        }
        const parts: string[] = []
        if (ownedToShare.length > 0) parts.push(`${ownedToShare.length} gedeeld`)
        if (ownedToUnshare.length > 0) parts.push(`${ownedToUnshare.length} niet meer gedeeld`)
        setFeedback({ type: "success", message: `${parts.join(", ")} met team.` })
        router.refresh()
      } catch (error) {
        setFeedback({
          type: "error",
          message:
            error instanceof Error ? error.message : "Deling bijwerken is mislukt.",
        })
      }
    })
  }

  const publishBatch = () => {
    setFeedback({ type: null, message: "" })
    startTransition(async () => {
      try {
        const response = await fetch("/api/blogs/publish/batch", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            blog_ids: ownedSelectedIds,
            site_ids: selectedSiteIds,
            wp_status: wpStatus,
          }),
        })
        const payload = (await response.json().catch(() => null)) as
          | BatchResponse
          | null
        if (!response.ok) {
          throw new Error(getErrorMessage(payload, "Batch publiceren is mislukt."))
        }
        if (!payload || !("requested" in payload)) {
          throw new Error("Onverwachte response van server.")
        }

        const blockedText =
          payload.blocked_duplicates > 0
            ? `, ${payload.blocked_duplicates} duplicaten overgeslagen`
            : ""
        setFeedback({
          type: "success",
          message: `${payload.queued} publicaties gestart${blockedText}.`,
        })
        setSelectedSiteIds([])
        setSelectedBlogs({})
        router.refresh()
      } catch (error) {
        setFeedback({
          type: "error",
          message:
            error instanceof Error ? error.message : "Batch publiceren is mislukt.",
        })
      }
    })
  }

  return (
    <div className="space-y-4">
      <div className="rounded-lg border p-4 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <label className="inline-flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={allSelected}
              ref={(element) => {
                if (element) {
                  element.indeterminate = selectedCount > 0 && !allSelected
                }
              }}
              onChange={(event) => toggleSelectAll(event.target.checked)}
              disabled={isSelectingAll}
            />
            {isSelectingAll
              ? "Selecteren..."
              : `Selecteer alle ${totalBlogs} blogs`}
            {selectedCount > 0 && (
              <span className="text-muted-foreground">
                ({selectedCount} geselecteerd)
              </span>
            )}
          </label>

          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={copySelectionLinks}
              disabled={selectedCount === 0}
              aria-label={
                copiedSelection
                  ? "Deel-links gekopieerd"
                  : "Kopieer deel-links van selectie"
              }
              title={
                copiedSelection
                  ? "Deel-links gekopieerd"
                  : "Kopieer deel-links van selectie"
              }
            >
              {copiedSelection ? <Check /> : <Link2 />}
              Kopieer links ({selectedCount})
            </Button>
            <Button
              variant="outline"
              onClick={shareBatch}
              disabled={ownedSelectedIds.length === 0 || isPending}
            >
              <Users />
              Deel met team ({ownedSelectedIds.length})
            </Button>
            <Button
              variant="outline"
              onClick={openBatchPanel}
              disabled={ownedSelectedIds.length === 0 || isPending}
            >
              Publiceer selectie ({ownedSelectedIds.length})
            </Button>
            {ownedSelectedIds.length > 0 && (
              <Button
                variant="destructive"
                onClick={deleteBatch}
                disabled={isPending}
              >
                {isPending ? "Verwijderen..." : `Verwijder selectie (${ownedSelectedIds.length})`}
              </Button>
            )}
          </div>
        </div>

        {sharedSelectedCount > 0 && (
          <p className="text-xs text-muted-foreground">
            {sharedSelectedCount} geselecteerde blog
            {sharedSelectedCount === 1 ? " is" : "s zijn"} gedeeld met jou; voor
            gedeelde blogs is alleen kopiëren mogelijk.
          </p>
        )}

        {showBatchPanel && (
          <div className="space-y-3 rounded-md border bg-muted/20 p-3">
            <p className="text-sm font-medium">Kies WordPress sites</p>
            {sites.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Geen actieve WordPress sites gevonden. Voeg eerst sites toe in
                Instellingen.
              </p>
            ) : (
              <div className="grid gap-2 md:grid-cols-2">
                {sites.map((site) => (
                  <label
                    key={site.id}
                    className="flex items-center justify-between gap-2 rounded-md border px-3 py-2 text-sm"
                  >
                    <span className="truncate">{site.name}</span>
                    <input
                      type="checkbox"
                      checked={selectedSiteIds.includes(site.id)}
                      onChange={(event) =>
                        toggleSiteSelection(site.id, event.target.checked)
                      }
                      disabled={isPending}
                    />
                  </label>
                ))}
              </div>
            )}

            <label className="flex items-center gap-2 text-sm">
              <span className="text-muted-foreground">Status:</span>
              <select
                value={wpStatus}
                onChange={(event) =>
                  setWpStatus(event.target.value as "draft" | "publish")
                }
                disabled={isPending}
                className="rounded-md border bg-background px-2 py-1 text-sm"
              >
                <option value="draft">Concept (draft)</option>
                <option value="publish">Gepubliceerd (publish)</option>
              </select>
            </label>

            <div className="flex justify-end gap-2">
              <Button
                variant="outline"
                onClick={() => setShowBatchPanel(false)}
                disabled={isPending}
              >
                Sluiten
              </Button>
              <Button
                onClick={publishBatch}
                disabled={
                  isPending ||
                  ownedSelectedIds.length === 0 ||
                  selectedSiteIds.length === 0
                }
              >
                {isPending ? "Publiceren..." : "Start batch publicatie"}
              </Button>
            </div>
          </div>
        )}

        {feedback.message && (
          <div
            className={`rounded-md border px-3 py-2 text-sm ${
              feedback.type === "success"
                ? "border-green-200 bg-green-50 text-green-700"
                : "border-red-200 bg-red-50 text-red-700"
            }`}
          >
            {feedback.message}
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
        {blogs.map((blog) => (
          <article key={blog.id} className="rounded-lg border bg-card p-4 space-y-3">
            <div className="space-y-2">
              <label className="inline-flex items-center gap-2 text-xs">
                <input
                  type="checkbox"
                  checked={Boolean(selectedBlogs[blog.id])}
                  onChange={(event) =>
                    toggleBlogSelection(blog, event.target.checked)
                  }
                />
                Selecteer
              </label>
              <div className="flex flex-wrap items-center gap-1">
                {blog.customerName && (
                  <span className="rounded-full bg-violet-100 px-2 py-1 text-[11px] font-medium text-violet-800 dark:bg-violet-900/30 dark:text-violet-300">
                    {blog.customerName}
                  </span>
                )}
                {!blog.isOwner && (
                  <span className="rounded-full bg-blue-100 px-2 py-1 text-[11px] font-medium text-blue-800 dark:bg-blue-900/30 dark:text-blue-300">
                    Gedeeld met jou
                  </span>
                )}
                {blog.isOwner && blog.isPublic && (
                  <span className="rounded-full bg-blue-100 px-2 py-1 text-[11px] font-medium text-blue-800 dark:bg-blue-900/30 dark:text-blue-300">
                    Gedeeld
                  </span>
                )}
              </div>
            </div>

            <h2 className="line-clamp-2 text-base font-semibold">{blog.title}</h2>
            <p className="text-sm text-muted-foreground">
              Aangemaakt op {blog.createdDate}
            </p>

            <div className="flex items-center gap-2 pt-1">
              <Button asChild size="sm" className="min-w-0 flex-1">
                <Link href={`/dashboard/blogs/${blog.id}`}>Open blog</Link>
              </Button>
              <Button
                type="button"
                variant="outline"
                size="icon-sm"
                onClick={() => copyShareLink(blog)}
                aria-label={
                  copiedShareBlogId === blog.id
                    ? "Gekopieerd"
                    : "Kopieer deel-link"
                }
                title={
                  copiedShareBlogId === blog.id
                    ? "Gekopieerd"
                    : "Kopieer deel-link"
                }
              >
                {copiedShareBlogId === blog.id ? <Check /> : <Link2 />}
              </Button>
            </div>
          </article>
        ))}
      </div>
    </div>
  )
}
