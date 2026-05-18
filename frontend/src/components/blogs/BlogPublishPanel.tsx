"use client"

import { useCallback, useEffect, useMemo, useState, useTransition } from "react"

import { Button } from "@/components/ui/button"
import {
  BlogImage,
  PublicationItem,
  PublishActionResponse,
  WordPressSite,
} from "@/lib/wordpress-types"

type SitesResponse =
  | {
      sites: WordPressSite[]
    }
  | {
      error: string
    }

type PublicationsResponse =
  | {
      publications: PublicationItem[]
    }
  | {
      error: string
    }

type ImagesResponse =
  | {
      images: BlogImage[]
    }
  | {
      error: string
    }

type PublishResponse =
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

function statusLabel(status: PublicationItem["status"]) {
  switch (status) {
    case "pending":
      return "In wachtrij"
    case "processing":
      return "Bezig"
    case "succeeded":
      return "Gepubliceerd"
    case "failed":
      return "Mislukt"
    case "blocked_duplicate":
      return "Al gepubliceerd"
    default:
      return status
  }
}

function statusClasses(status: PublicationItem["status"]) {
  switch (status) {
    case "succeeded":
      return "bg-green-100 text-green-700"
    case "failed":
      return "bg-red-100 text-red-700"
    case "processing":
      return "bg-blue-100 text-blue-700"
    case "pending":
      return "bg-zinc-100 text-zinc-700"
    case "blocked_duplicate":
      return "bg-amber-100 text-amber-700"
    default:
      return "bg-zinc-100 text-zinc-700"
  }
}

function formatDate(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return "-"
  }
  return new Intl.DateTimeFormat("nl-NL", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date)
}

export function BlogPublishPanel({ blogId }: { blogId: string }) {
  const [sites, setSites] = useState<WordPressSite[]>([])
  const [publications, setPublications] = useState<PublicationItem[]>([])
  const [hasPrimaryImage, setHasPrimaryImage] = useState(false)
  const [selectedSiteIds, setSelectedSiteIds] = useState<string[]>([])
  const [wpStatus, setWpStatus] = useState<"draft" | "publish">("draft")
  const [isLoading, setIsLoading] = useState(true)
  const [feedback, setFeedback] = useState<{
    type: "success" | "error" | null
    message: string
  }>({ type: null, message: "" })
  const [isPending, startTransition] = useTransition()

  const siteMap = useMemo(() => {
    return new Map(sites.map((site) => [site.id, site]))
  }, [sites])

  const hasInFlightPublications = useMemo(() => {
    return publications.some(
      (publication) =>
        publication.status === "pending" || publication.status === "processing"
    )
  }, [publications])

  const loadSites = useCallback(async () => {
    const response = await fetch("/api/wordpress/sites", {
      method: "GET",
      cache: "no-store",
    })
    const payload = (await response.json().catch(() => null)) as
      | SitesResponse
      | null
    if (!response.ok) {
      throw new Error(getErrorMessage(payload, "Kon WordPress sites niet laden."))
    }
    const nextSites =
      payload && "sites" in payload && Array.isArray(payload.sites)
        ? payload.sites.filter((site) => site.is_active)
        : []
    setSites(nextSites)
  }, [])

  const loadPublications = useCallback(async () => {
    const response = await fetch(
      `/api/publications?blog_id=${encodeURIComponent(blogId)}&limit=200`,
      {
        method: "GET",
        cache: "no-store",
      }
    )
    const payload = (await response.json().catch(() => null)) as
      | PublicationsResponse
      | null
    if (!response.ok) {
      throw new Error(getErrorMessage(payload, "Kon publicaties niet laden."))
    }
    const nextPublications =
      payload && "publications" in payload && Array.isArray(payload.publications)
        ? payload.publications
        : []
    setPublications(nextPublications)
  }, [blogId])

  const loadImages = useCallback(async () => {
    const response = await fetch(`/api/blogs/${encodeURIComponent(blogId)}/images`, {
      method: "GET",
      cache: "no-store",
    })
    const payload = (await response.json().catch(() => null)) as
      | ImagesResponse
      | null
    if (!response.ok) {
      throw new Error(getErrorMessage(payload, "Kon afbeeldingen niet laden."))
    }
    const images =
      payload && "images" in payload && Array.isArray(payload.images)
        ? payload.images
        : []
    setHasPrimaryImage(images.some((image) => image.is_primary))
  }, [blogId])

  const refreshData = useCallback(async () => {
    setIsLoading(true)
    try {
      await Promise.all([loadSites(), loadPublications(), loadImages()])
    } finally {
      setIsLoading(false)
    }
  }, [loadImages, loadPublications, loadSites])

  useEffect(() => {
    refreshData().catch((error) => {
      setFeedback({
        type: "error",
        message:
          error instanceof Error
            ? error.message
            : "Kon WordPress gegevens niet laden.",
      })
      setIsLoading(false)
    })
  }, [refreshData])

  useEffect(() => {
    if (!hasInFlightPublications) {
      return
    }

    const interval = window.setInterval(() => {
      loadPublications().catch(() => {
        // silent background polling errors
      })
    }, 8000)

    return () => {
      window.clearInterval(interval)
    }
  }, [hasInFlightPublications, loadPublications])

  const toggleSite = (siteId: string, checked: boolean) => {
    setSelectedSiteIds((current) => {
      if (checked) {
        return current.includes(siteId) ? current : [...current, siteId]
      }
      return current.filter((value) => value !== siteId)
    })
  }

  const publishToSelectedSites = () => {
    setFeedback({ type: null, message: "" })
    startTransition(async () => {
      try {
        const response = await fetch(`/api/blogs/${blogId}/publish`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            site_ids: selectedSiteIds,
            wp_status: wpStatus,
          }),
        })
        const payload = (await response.json().catch(() => null)) as
          | PublishResponse
          | null
        if (!response.ok) {
          throw new Error(getErrorMessage(payload, "Publiceren is mislukt."))
        }

        if (!payload || !("requested" in payload)) {
          throw new Error("Onverwachte response van server.")
        }

        const blockedPart =
          payload.blocked_duplicates > 0
            ? `, ${payload.blocked_duplicates} al eerder gepubliceerd`
            : ""
        setFeedback({
          type: "success",
          message: `${payload.queued} publicatie(s) gestart${blockedPart}.`,
        })
        setSelectedSiteIds([])
        await loadPublications()
      } catch (error) {
        setFeedback({
          type: "error",
          message:
            error instanceof Error ? error.message : "Publiceren is mislukt.",
        })
      }
    })
  }

  return (
    <section className="space-y-4 rounded-lg border bg-card p-5">
      <div className="space-y-1">
        <h2 className="text-lg font-semibold">Publiceer naar WordPress</h2>
        <p className="text-sm text-muted-foreground">
          Kies één of meerdere sites om deze blog als{" "}
          {wpStatus === "draft" ? "concept" : "gepubliceerd"} te plaatsen.
        </p>
        <p className="text-xs text-muted-foreground">
          {hasPrimaryImage
            ? "Primaire afbeelding beschikbaar voor featured image."
            : "Nog geen primaire afbeelding: publicatie gaat door zonder uitgelichte afbeelding."}
        </p>
      </div>

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

      <div className="space-y-3 rounded-md border p-3">
        <div className="space-y-2">
          {isLoading ? (
            <p className="text-sm text-muted-foreground">WordPress sites laden...</p>
          ) : sites.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Geen actieve WordPress sites. Voeg eerst sites toe in Instellingen.
            </p>
          ) : (
            sites.map((site) => (
              <label
                key={site.id}
                className="flex items-center justify-between gap-3 rounded-md border px-3 py-2 text-sm"
              >
                <div className="space-y-0.5">
                  <p className="font-medium">{site.name}</p>
                  <p className="text-xs text-muted-foreground">{site.base_url}</p>
                </div>
                <input
                  type="checkbox"
                  checked={selectedSiteIds.includes(site.id)}
                  onChange={(event) => toggleSite(site.id, event.target.checked)}
                  disabled={isPending}
                />
              </label>
            ))
          )}
        </div>

        <div className="flex items-center justify-between gap-3">
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
          <Button
            onClick={publishToSelectedSites}
            disabled={isPending || selectedSiteIds.length === 0}
          >
            {isPending ? "Publiceren..." : "Publiceer geselecteerde sites"}
          </Button>
        </div>
      </div>

      <div className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <h3 className="text-sm font-semibold">Publicatiegeschiedenis</h3>
          <Button variant="outline" size="sm" onClick={() => refreshData()} disabled={isPending}>
            Vernieuwen
          </Button>
        </div>

        {publications.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Deze blog is nog niet naar WordPress gepost.
          </p>
        ) : (
          <div className="space-y-2">
            {publications.map((publication) => {
              const site = siteMap.get(publication.wordpress_site_id)
              return (
                <article
                  key={publication.id}
                  className="rounded-md border px-3 py-2 text-sm"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="font-medium">
                      {site?.name || publication.wordpress_site_id}
                    </p>
                    <span
                      className={`rounded-full px-2 py-1 text-xs font-medium ${statusClasses(
                        publication.status
                      )}`}
                    >
                      {statusLabel(publication.status)}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {formatDate(publication.created_at)}
                  </p>
                  {publication.wp_post_url && (
                    <p className="mt-1">
                      <a
                        href={publication.wp_post_url}
                        target="_blank"
                        rel="noreferrer noopener"
                        className="text-xs underline underline-offset-2"
                      >
                        Open WordPress post
                      </a>
                    </p>
                  )}
                  {publication.error_message && (
                    <p className="mt-1 text-xs text-red-600">
                      {publication.error_message}
                    </p>
                  )}
                  {publication.warning_message && (
                    <p className="mt-1 text-xs text-amber-700">
                      {publication.warning_message}
                    </p>
                  )}
                  {publication.wp_media_id && (
                    <p className="mt-1 text-xs text-muted-foreground">
                      WP media id: {publication.wp_media_id}
                    </p>
                  )}
                </article>
              )
            })}
          </div>
        )}
      </div>
    </section>
  )
}
