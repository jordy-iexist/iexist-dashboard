"use client"

import Link from "next/link"
import { useEffect, useMemo, useRef, useState, useTransition } from "react"
import { useRouter } from "next/navigation"
import { Check, Link2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import { PublishActionResponse, WordPressSite } from "@/lib/wordpress-types"

type PublishSummary = {
  total: number
  succeeded: number
  failed: number
  pending: number
  processing: number
}

const EMPTY_PUBLISH_SUMMARY: PublishSummary = {
  total: 0,
  succeeded: 0,
  failed: 0,
  pending: 0,
  processing: 0,
}

export type BlogListItem = {
  id: string
  shareToken: string
  title: string
  createdAt: string
  filename: string
  words: string
  anchor1: string
  anchor2: string
  preview: string
  publication: PublishSummary
  published_at: string | null
  isPublic: boolean
  isOwner: boolean
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

function publicationLabel(blog: BlogListItem) {
  if (blog.published_at) {
    return "Gepubliceerd"
  }
  const safeSummary = blog.publication ?? EMPTY_PUBLISH_SUMMARY
  if (safeSummary.total === 0) {
    return "Nog niet gepubliceerd"
  }
  const inFlight = safeSummary.pending + safeSummary.processing
  if (inFlight > 0) {
    return `${safeSummary.succeeded} geslaagd · ${safeSummary.failed} mislukt · ${inFlight} lopend`
  }
  if (safeSummary.failed > 0 && safeSummary.succeeded === 0) {
    return `${safeSummary.failed} mislukt`
  }
  if (safeSummary.succeeded > 0 && safeSummary.failed === 0) {
    return `${safeSummary.succeeded} gepubliceerd`
  }
  return `${safeSummary.succeeded} geslaagd · ${safeSummary.failed} mislukt`
}

function publicationBadgeClasses(blog: BlogListItem) {
  if (blog.published_at) {
    return "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300"
  }
  const safeSummary = blog.publication ?? EMPTY_PUBLISH_SUMMARY
  const inFlight = safeSummary.pending + safeSummary.processing
  if (safeSummary.total === 0) return "bg-muted text-muted-foreground"
  if (inFlight > 0) return "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300"
  if (safeSummary.failed > 0 && safeSummary.succeeded === 0)
    return "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300"
  if (safeSummary.succeeded > 0 && safeSummary.failed === 0)
    return "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300"
  return "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300"
}

export function BlogsBatchPublishList({ blogs }: { blogs: BlogListItem[] }) {
  const router = useRouter()
  const [selectedBlogIds, setSelectedBlogIds] = useState<string[]>([])
  const [selectedSiteIds, setSelectedSiteIds] = useState<string[]>([])
  const [wpStatus, setWpStatus] = useState<"draft" | "publish">("draft")
  const [sites, setSites] = useState<WordPressSite[]>([])
  const [showBatchPanel, setShowBatchPanel] = useState(false)
  const [feedback, setFeedback] = useState<{
    type: "success" | "error" | null
    message: string
  }>({ type: null, message: "" })
  const [copiedShareBlogId, setCopiedShareBlogId] = useState<string | null>(null)
  const [isPending, startTransition] = useTransition()
  const pollingIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const copyResetTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

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
    }
  }, [])

  const ownedBlogs = useMemo(
    () => blogs.filter((blog) => blog.isOwner),
    [blogs]
  )

  const allSelected = useMemo(
    () => ownedBlogs.length > 0 && selectedBlogIds.length === ownedBlogs.length,
    [ownedBlogs.length, selectedBlogIds.length]
  )

  const toggleBlogSelection = (blogId: string, checked: boolean) => {
    setSelectedBlogIds((current) => {
      if (checked) {
        return current.includes(blogId) ? current : [...current, blogId]
      }
      return current.filter((value) => value !== blogId)
    })
  }

  const toggleSelectAll = (checked: boolean) => {
    if (checked) {
      setSelectedBlogIds(ownedBlogs.map((blog) => blog.id))
      return
    }
    setSelectedBlogIds([])
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

  const deleteBatch = () => {
    if (selectedBlogIds.length === 0) return
    const confirmed = window.confirm(
      `Weet je zeker dat je ${selectedBlogIds.length} blog(s) wilt verwijderen? Dit kan niet ongedaan gemaakt worden.`
    )
    if (!confirmed) return

    setFeedback({ type: null, message: "" })
    startTransition(async () => {
      try {
        const response = await fetch("/api/blogs/delete/batch", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ blog_ids: selectedBlogIds }),
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
        setSelectedBlogIds([])
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
            blog_ids: selectedBlogIds,
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
        setSelectedBlogIds([])
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
              onChange={(event) => toggleSelectAll(event.target.checked)}
            />
            Selecteer alles op deze pagina
          </label>

          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="outline"
              onClick={openBatchPanel}
              disabled={selectedBlogIds.length === 0 || isPending}
            >
              Publiceer selectie ({selectedBlogIds.length})
            </Button>
            {selectedBlogIds.length > 0 && (
              <Button
                variant="destructive"
                onClick={deleteBatch}
                disabled={isPending}
              >
                {isPending ? "Verwijderen..." : `Verwijder selectie (${selectedBlogIds.length})`}
              </Button>
            )}
          </div>
        </div>

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
                  selectedBlogIds.length === 0 ||
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
            <div className="flex items-start justify-between gap-2">
              {blog.isOwner ? (
                <label className="inline-flex items-center gap-2 text-xs">
                  <input
                    type="checkbox"
                    checked={selectedBlogIds.includes(blog.id)}
                    onChange={(event) =>
                      toggleBlogSelection(blog.id, event.target.checked)
                    }
                  />
                  Selecteer
                </label>
              ) : (
                <span className="rounded-full bg-blue-100 px-2 py-1 text-[11px] font-medium text-blue-800 dark:bg-blue-900/30 dark:text-blue-300">
                  Gedeeld met jou
                </span>
              )}
              <div className="flex items-center gap-1">
                {blog.isOwner && blog.isPublic && (
                  <span className="rounded-full bg-blue-100 px-2 py-1 text-[11px] font-medium text-blue-800 dark:bg-blue-900/30 dark:text-blue-300">
                    Gedeeld
                  </span>
                )}
                <span
                  className={`rounded-full px-2 py-1 text-[11px] font-medium ${publicationBadgeClasses(blog)}`}
                >
                  {publicationLabel(blog)}
                </span>
              </div>
            </div>

            <h2 className="line-clamp-2 text-base font-semibold">{blog.title}</h2>

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
