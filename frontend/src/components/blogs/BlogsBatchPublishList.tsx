"use client"

import Link from "next/link"
import { useEffect, useMemo, useRef, useState, useTransition } from "react"
import { useRouter } from "next/navigation"
import { Check, LayoutGrid, Link2, List, Users } from "lucide-react"

import {
  WordPressCategoryPicker,
  isFutureLocalDateTime,
  localDateTimeToIso,
} from "@/components/blogs/WordPressCategoryPicker"
import { WordPressSiteMultiSelect } from "@/components/blogs/WordPressSiteMultiSelect"
import { Button } from "@/components/ui/button"
import { type BlogsIdsResponse } from "@/lib/blog-types"
import { BLOGS_VIEW_COOKIE, type BlogsView } from "@/lib/blogs-view"
import {
  PublishActionResponse,
  WordPressPostStatus,
  WordPressSite,
} from "@/lib/wordpress-types"

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
  placedDate: string | null
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

type BlogPublishOptions = {
  siteIds: string[]
  scheduledAt: string
  categoryIdsBySite: Record<string, number[]>
}

const EMPTY_PUBLISH_OPTIONS: BlogPublishOptions = {
  siteIds: [],
  scheduledAt: "",
  categoryIdsBySite: {},
}

// 1 jaar; de weergavekeuze is een blijvende voorkeur.
const VIEW_COOKIE_MAX_AGE = 60 * 60 * 24 * 365

const VIEW_OPTIONS: { value: BlogsView; label: string; icon: typeof List }[] = [
  { value: "list", label: "Lijst", icon: List },
  { value: "grid", label: "Kaarten", icon: LayoutGrid },
]

export function BlogsBatchPublishList({
  blogs,
  totalBlogs,
  filters,
  initialView,
}: {
  blogs: BlogListItem[]
  totalBlogs: number
  filters: BlogListFilters
  initialView: BlogsView
}) {
  const router = useRouter()
  const [view, setView] = useState<BlogsView>(initialView)
  const [selectedBlogs, setSelectedBlogs] = useState<
    Record<string, SelectedBlogInfo>
  >({})
  const [isSelectingAll, setIsSelectingAll] = useState(false)
  const [wpStatus, setWpStatus] = useState<WordPressPostStatus>("draft")
  const [publishOptions, setPublishOptions] = useState<
    Record<string, BlogPublishOptions>
  >({})
  const [sites, setSites] = useState<WordPressSite[]>([])
  const [showBatchPanel, setShowBatchPanel] = useState(false)
  const [feedback, setFeedback] = useState<{
    type: "success" | "error" | null
    message: string
  }>({ type: null, message: "" })
  const [copiedShareBlogId, setCopiedShareBlogId] = useState<string | null>(null)
  const [copiedSelection, setCopiedSelection] = useState(false)
  const [placedOverrides, setPlacedOverrides] = useState<
    Record<string, { isPublished: boolean; placedDate: string | null }>
  >({})
  const [savingPlacedIds, setSavingPlacedIds] = useState<Record<string, boolean>>({})
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

  // Zodra verse serverdata de optimistische geplaatst-status bevestigt (na
  // router.refresh()), laten we de lokale override los.
  useEffect(() => {
    setPlacedOverrides((current) => {
      if (Object.keys(current).length === 0) return current
      let changed = false
      const next = { ...current }
      for (const blog of blogs) {
        const override = next[blog.id]
        if (override && override.isPublished === Boolean(blog.published_at)) {
          delete next[blog.id]
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

  const blogTitles = useMemo(
    () => new Map(blogs.map((blog) => [blog.id, blog.title])),
    [blogs]
  )

  const sitesById = useMemo(
    () => new Map(sites.map((site) => [site.id, site])),
    [sites]
  )

  const missingSiteCount = useMemo(
    () =>
      ownedSelectedIds.filter(
        (blogId) => (publishOptions[blogId]?.siteIds ?? []).length === 0
      ).length,
    [ownedSelectedIds, publishOptions]
  )

  const missingScheduleCount = useMemo(() => {
    if (wpStatus !== "future") return 0
    return ownedSelectedIds.filter(
      (blogId) => !isFutureLocalDateTime(publishOptions[blogId]?.scheduledAt ?? "")
    ).length
  }, [ownedSelectedIds, publishOptions, wpStatus])

  const updatePublishOptions = (
    blogId: string,
    update: (current: BlogPublishOptions) => BlogPublishOptions
  ) => {
    setPublishOptions((current) => ({
      ...current,
      [blogId]: update(current[blogId] ?? EMPTY_PUBLISH_OPTIONS),
    }))
  }

  const applyOptionsToAll = (sourceBlogId: string) => {
    const source = publishOptions[sourceBlogId] ?? EMPTY_PUBLISH_OPTIONS
    setPublishOptions((current) => {
      const next = { ...current }
      for (const blogId of ownedSelectedIds) {
        next[blogId] = {
          siteIds: [...source.siteIds],
          scheduledAt: source.scheduledAt,
          categoryIdsBySite: { ...source.categoryIdsBySite },
        }
      }
      return next
    })
  }

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

  const toggleBlogSite = (blogId: string, siteId: string, checked: boolean) => {
    updatePublishOptions(blogId, (current) => {
      if (checked) {
        return current.siteIds.includes(siteId)
          ? current
          : { ...current, siteIds: [...current.siteIds, siteId] }
      }
      const categoryIdsBySite = { ...current.categoryIdsBySite }
      delete categoryIdsBySite[siteId]
      return {
        ...current,
        siteIds: current.siteIds.filter((value) => value !== siteId),
        categoryIdsBySite,
      }
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

  const changeView = (next: BlogsView) => {
    setView(next)
    document.cookie = `${BLOGS_VIEW_COOKIE}=${next}; path=/; max-age=${VIEW_COOKIE_MAX_AGE}`
  }

  // Optimistische override gaat voor op de serverdata totdat die bevestigd is.
  const getPlacedState = (blog: BlogListItem) => {
    const placedOverride = placedOverrides[blog.id]
    return {
      isPlaced: placedOverride
        ? placedOverride.isPublished
        : Boolean(blog.published_at),
      placedDate: placedOverride ? placedOverride.placedDate : blog.placedDate,
      isSavingPlaced: Boolean(savingPlacedIds[blog.id]),
    }
  }

  const togglePlaced = (blog: BlogListItem, checked: boolean) => {
    if (!blog.isOwner) return
    const previousOverride = placedOverrides[blog.id]
    setFeedback({ type: null, message: "" })
    setPlacedOverrides((current) => ({
      ...current,
      [blog.id]: { isPublished: checked, placedDate: checked ? blog.placedDate : null },
    }))
    setSavingPlacedIds((current) => ({ ...current, [blog.id]: true }))
    void (async () => {
      try {
        const response = await fetch(`/api/blogs/${blog.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ is_published: checked }),
        })
        const payload = await response.json().catch(() => null)
        if (!response.ok) {
          throw new Error(
            getErrorMessage(payload, "Geplaatst-status aanpassen is mislukt.")
          )
        }
        router.refresh()
      } catch (error) {
        setPlacedOverrides((current) => {
          const next = { ...current }
          if (previousOverride) {
            next[blog.id] = previousOverride
          } else {
            delete next[blog.id]
          }
          return next
        })
        setFeedback({
          type: "error",
          message:
            error instanceof Error
              ? error.message
              : "Geplaatst-status aanpassen is mislukt.",
        })
      } finally {
        setSavingPlacedIds((current) => {
          const next = { ...current }
          delete next[blog.id]
          return next
        })
      }
    })()
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
            wp_status: wpStatus,
            items: ownedSelectedIds.map((blogId) => {
              const options = publishOptions[blogId] ?? EMPTY_PUBLISH_OPTIONS
              return {
                blog_id: blogId,
                site_ids: options.siteIds,
                scheduled_at:
                  wpStatus === "publish"
                    ? null
                    : localDateTimeToIso(options.scheduledAt),
                category_ids_by_site: Object.fromEntries(
                  options.siteIds.map((siteId) => [
                    siteId,
                    options.categoryIdsBySite[siteId] ?? [],
                  ])
                ),
              }
            }),
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
        setSelectedBlogs({})
        setPublishOptions({})
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
            <div
              role="group"
              aria-label="Weergave"
              className="inline-flex items-center gap-0.5 rounded-md border p-0.5"
            >
              {VIEW_OPTIONS.map((option) => {
                const Icon = option.icon
                const isActive = view === option.value
                return (
                  <Button
                    key={option.value}
                    type="button"
                    variant={isActive ? "outline" : "ghost"}
                    size="icon-sm"
                    onClick={() => changeView(option.value)}
                    aria-pressed={isActive}
                    aria-label={option.label}
                    title={option.label}
                  >
                    <Icon />
                  </Button>
                )
              })}
            </div>
            <Button
              type="button"
              variant="secondary"
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
              variant="secondary"
              onClick={shareBatch}
              disabled={ownedSelectedIds.length === 0 || isPending}
            >
              <Users />
              Deel met team ({ownedSelectedIds.length})
            </Button>
            <Button
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
          <div className="space-y-4 border-t pt-4">
            {sites.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Geen actieve WordPress sites gevonden. Voeg eerst sites toe in{" "}
                <Link href="/dashboard/settings/wordpress" className="underline underline-offset-2">
                  Instellingen
                </Link>
                .
              </p>
            ) : (
              <div className="flex flex-wrap items-center gap-3">
                <label className="flex items-center gap-2 text-sm">
                  <span className="text-muted-foreground">Status:</span>
                  <select
                    value={wpStatus}
                    onChange={(event) =>
                      setWpStatus(event.target.value as WordPressPostStatus)
                    }
                    disabled={isPending}
                    className="h-9 rounded-md border bg-background px-2 text-sm"
                  >
                    <option value="draft">Concept (draft)</option>
                    <option value="publish">Direct publiceren (publish)</option>
                    <option value="future">Inplannen (future)</option>
                  </select>
                </label>
              </div>
            )}

            {ownedSelectedIds.length > 0 && sites.length > 0 && (
              <div className="space-y-2">
                <p className="text-sm font-medium">
                  {wpStatus === "publish"
                    ? "Sites en categorieën per blog"
                    : "Sites, datum en categorieën per blog"}
                </p>
                <div className="max-h-[32rem] divide-y overflow-y-auto pr-1">
                  {ownedSelectedIds.map((blogId) => {
                    const options = publishOptions[blogId] ?? EMPTY_PUBLISH_OPTIONS
                    const needsDate =
                      wpStatus === "future" &&
                      !isFutureLocalDateTime(options.scheduledAt)
                    const blogSites = options.siteIds
                      .map((siteId) => sitesById.get(siteId))
                      .filter((site): site is WordPressSite => Boolean(site))
                    return (
                      <div
                        key={blogId}
                        className="space-y-2 py-3 first:pt-0"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <p className="min-w-0 flex-1 truncate text-sm font-medium">
                            {blogTitles.get(blogId) ?? `Blog ${blogId.slice(0, 8)}`}
                          </p>
                          {wpStatus !== "publish" && (
                            <label className="flex items-center gap-2 text-xs">
                              <span className="text-muted-foreground">
                                {wpStatus === "future" ? "Publiceren op:" : "Postdatum:"}
                              </span>
                              <input
                                type="datetime-local"
                                value={options.scheduledAt}
                                onChange={(event) =>
                                  updatePublishOptions(blogId, (current) => ({
                                    ...current,
                                    scheduledAt: event.target.value,
                                  }))
                                }
                                disabled={isPending}
                                className={`rounded-md border bg-background px-2 py-1 text-sm ${
                                  needsDate ? "border-amber-400" : ""
                                }`}
                              />
                            </label>
                          )}
                          {ownedSelectedIds.length > 1 && (
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              onClick={() => applyOptionsToAll(blogId)}
                              disabled={isPending}
                            >
                              Toepassen op alle
                            </Button>
                          )}
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                          <WordPressSiteMultiSelect
                            sites={sites}
                            selectedIds={options.siteIds}
                            onToggle={(siteId, checked) =>
                              toggleBlogSite(blogId, siteId, checked)
                            }
                            disabled={isPending}
                          />
                          {blogSites.length === 0 && (
                            <span className="text-xs text-amber-700">
                              Kies minimaal één site.
                            </span>
                          )}
                        </div>
                        <div className="space-y-2">
                          {blogSites.map((site) => (
                            <WordPressCategoryPicker
                              key={site.id}
                              variant="chips"
                              siteId={site.id}
                              siteName={blogSites.length > 1 ? site.name : undefined}
                              selectedIds={options.categoryIdsBySite[site.id] ?? []}
                              onChange={(ids) =>
                                updatePublishOptions(blogId, (current) => ({
                                  ...current,
                                  categoryIdsBySite: {
                                    ...current.categoryIdsBySite,
                                    [site.id]: ids,
                                  },
                                }))
                              }
                              disabled={isPending}
                            />
                          ))}
                        </div>
                      </div>
                    )
                  })}
                </div>
                {missingSiteCount > 0 && (
                  <p className="text-xs text-amber-700">
                    {missingSiteCount} blog(s) hebben nog geen WordPress site.
                  </p>
                )}
                {missingScheduleCount > 0 && (
                  <p className="text-xs text-amber-700">
                    {missingScheduleCount} blog(s) hebben nog geen datum in de
                    toekomst.
                  </p>
                )}
              </div>
            )}

            <div className="flex justify-end gap-2">
              <Button
                variant="secondary"
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
                  missingSiteCount > 0 ||
                  missingScheduleCount > 0
                }
              >
                {isPending
                  ? "Publiceren..."
                  : wpStatus === "future"
                    ? "Start batch inplannen"
                    : "Start batch publicatie"}
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

      {view === "list" ? (
        <div className="divide-y rounded-lg border bg-card">
          <div className="hidden px-4 py-2 text-xs font-medium text-muted-foreground md:grid md:grid-cols-[1rem_minmax(0,1fr)_10rem_9rem_12rem_7rem] md:items-center md:gap-3">
            <span aria-hidden />
            <span>Titel</span>
            <span>Klant</span>
            <span>Aangemaakt</span>
            <span>Geplaatst</span>
            <span aria-hidden />
          </div>
          {blogs.map((blog) => {
            const { isPlaced, placedDate, isSavingPlaced } = getPlacedState(blog)
            const isSelected = Boolean(selectedBlogs[blog.id])

            return (
              <div
                key={blog.id}
                className={`flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2.5 transition-colors hover:bg-muted/50 md:grid md:grid-cols-[1rem_minmax(0,1fr)_10rem_9rem_12rem_7rem] ${
                  isSelected ? "bg-muted/40" : ""
                }`}
              >
                <input
                  type="checkbox"
                  checked={isSelected}
                  onChange={(event) =>
                    toggleBlogSelection(blog, event.target.checked)
                  }
                  aria-label={`Selecteer ${blog.title}`}
                />
                <div className="flex min-w-0 flex-1 items-center gap-2">
                  <Link
                    href={`/dashboard/blogs/${blog.id}`}
                    className="truncate text-sm font-medium hover:underline"
                    title={blog.title}
                  >
                    {blog.title}
                  </Link>
                  {!blog.isOwner && (
                    <span className="shrink-0 rounded-full bg-blue-100 px-2 py-0.5 text-[11px] font-medium text-blue-800 dark:bg-blue-900/30 dark:text-blue-300">
                      Gedeeld met jou
                    </span>
                  )}
                  {blog.isOwner && blog.isPublic && (
                    <span className="shrink-0 rounded-full bg-blue-100 px-2 py-0.5 text-[11px] font-medium text-blue-800 dark:bg-blue-900/30 dark:text-blue-300">
                      Gedeeld
                    </span>
                  )}
                </div>
                <div className="min-w-0">
                  {blog.customerName ? (
                    <span
                      className="inline-block max-w-full truncate rounded-full bg-violet-100 px-2 py-0.5 align-middle text-[11px] font-medium text-violet-800 dark:bg-violet-900/30 dark:text-violet-300"
                      title={blog.customerName}
                    >
                      {blog.customerName}
                    </span>
                  ) : (
                    <span className="hidden text-xs text-muted-foreground md:inline">
                      -
                    </span>
                  )}
                </div>
                <span className="text-xs text-muted-foreground">
                  {blog.createdDate}
                </span>
                <label
                  className="inline-flex items-center gap-2 text-xs"
                  title={
                    blog.isOwner
                      ? undefined
                      : "Alleen de eigenaar kan dit aanpassen."
                  }
                >
                  <input
                    type="checkbox"
                    checked={isPlaced}
                    disabled={!blog.isOwner || isSavingPlaced}
                    onChange={(event) =>
                      togglePlaced(blog, event.target.checked)
                    }
                  />
                  <span
                    className={
                      isPlaced
                        ? "text-green-700 dark:text-green-400"
                        : "text-muted-foreground"
                    }
                  >
                    {isPlaced
                      ? placedDate
                        ? `Geplaatst op ${placedDate}`
                        : "Geplaatst"
                      : "Niet geplaatst"}
                  </span>
                </label>
                <div className="ml-auto flex items-center justify-end gap-2">
                  <Button asChild size="sm" variant="outline">
                    <Link href={`/dashboard/blogs/${blog.id}`}>Open</Link>
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
              </div>
            )
          })}
        </div>
      ) : (
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
        {blogs.map((blog) => {
          const { isPlaced, placedDate, isSavingPlaced } = getPlacedState(blog)

          return (
          <article key={blog.id} className="rounded-lg border bg-card p-4 space-y-3">
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-3">
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
                <label
                  className="inline-flex items-center gap-2 text-xs"
                  title={
                    blog.isOwner
                      ? undefined
                      : "Alleen de eigenaar kan dit aanpassen."
                  }
                >
                  <input
                    type="checkbox"
                    checked={isPlaced}
                    disabled={!blog.isOwner || isSavingPlaced}
                    onChange={(event) =>
                      togglePlaced(blog, event.target.checked)
                    }
                  />
                  Geplaatst
                </label>
              </div>
              <div className="flex flex-wrap items-center gap-1">
                {blog.customerName && (
                  <span className="rounded-full bg-violet-100 px-2 py-1 text-[11px] font-medium text-violet-800 dark:bg-violet-900/30 dark:text-violet-300">
                    {blog.customerName}
                  </span>
                )}
                {isPlaced && (
                  <span className="rounded-full bg-green-100 px-2 py-1 text-[11px] font-medium text-green-800 dark:bg-green-900/30 dark:text-green-300">
                    {placedDate ? `Geplaatst op ${placedDate}` : "Geplaatst"}
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
          )
        })}
      </div>
      )}
    </div>
  )
}
