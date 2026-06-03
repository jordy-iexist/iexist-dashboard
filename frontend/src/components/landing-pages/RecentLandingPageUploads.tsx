"use client"

import { useEffect, useRef, useState } from "react"
import { Ban, Loader2, X } from "lucide-react"

import { Skeleton } from "@/components/ui/skeleton"
import { type LandingPageRecentUploadItem } from "@/lib/landing-page-types"

type FinalStatus = LandingPageRecentUploadItem["final_status"]

function formatDate(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return "-"
  return new Intl.DateTimeFormat("nl-NL", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date)
}

function statusLabel(status: FinalStatus) {
  switch (status) {
    case "processing":
      return "Bezig"
    case "completed":
      return "Voltooid"
    case "completed_with_errors":
      return "Voltooid met fouten"
    case "canceled":
      return "Geannuleerd"
  }
}

function statusBadgeClasses(status: FinalStatus) {
  switch (status) {
    case "processing":
      return "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300"
    case "completed":
      return "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300"
    case "completed_with_errors":
      return "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300"
    case "canceled":
      return "bg-muted text-muted-foreground"
  }
}

export function RecentLandingPageUploads() {
  const [uploads, setUploads] = useState<LandingPageRecentUploadItem[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [cancelingIds, setCancelingIds] = useState<Set<string>>(new Set())
  const isFetchingRef = useRef(false)

  const handleDismiss = async (uploadId: string) => {
    const previous = uploads
    setUploads((prev) => prev.filter((u) => u.upload_id !== uploadId))
    try {
      const res = await fetch(`/api/landing-pages/uploads/${uploadId}/dismiss`, { method: "POST" })
      if (!res.ok) {
        setUploads(previous)
        setError("Verbergen mislukt.")
      }
    } catch {
      setUploads(previous)
      setError("Verbergen mislukt.")
    }
  }

  const handleCancel = async (uploadId: string) => {
    if (cancelingIds.has(uploadId)) return
    if (!confirm("Weet je zeker dat je deze upload wil annuleren?")) return

    const previous = uploads
    setCancelingIds((prev) => new Set(prev).add(uploadId))
    setUploads((prev) =>
      prev.map((u) =>
        u.upload_id === uploadId ? { ...u, final_status: "canceled" as FinalStatus } : u
      )
    )

    try {
      const res = await fetch(`/api/landing-pages/uploads/${uploadId}/cancel`, { method: "POST" })
      if (!res.ok) {
        setUploads(previous)
        const data = await res.json().catch(() => null)
        const message =
          data && typeof (data as { error?: string }).error === "string"
            ? (data as { error: string }).error
            : "Annuleren mislukt."
        setError(message)
      }
    } catch {
      setUploads(previous)
      setError("Annuleren mislukt.")
    } finally {
      setCancelingIds((prev) => {
        const next = new Set(prev)
        next.delete(uploadId)
        return next
      })
    }
  }

  const fetchUploads = async (initial = false) => {
    if (isFetchingRef.current) return
    isFetchingRef.current = true
    try {
      const res = await fetch("/api/landing-pages/uploads", { cache: "no-store" })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        setError((body as { error?: string }).error ?? "Uploads ophalen mislukt.")
        return
      }
      const data: { uploads: LandingPageRecentUploadItem[] } = await res.json()
      setUploads(data.uploads)
      setError(null)
    } catch {
      setError("Kon recente uploads niet laden.")
    } finally {
      isFetchingRef.current = false
      if (initial) setIsLoading(false)
    }
  }

  useEffect(() => {
    fetchUploads(true)
    const interval = setInterval(() => fetchUploads(), 8000)
    return () => clearInterval(interval)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (isLoading) {
    return (
      <div className="space-y-3">
        <h2 className="text-lg font-semibold">Recente uploads</h2>
        <div className="space-y-2">
          {[...Array(3)].map((_, i) => (
            <Skeleton key={i} className="h-16 w-full" />
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <h2 className="text-lg font-semibold">Recente uploads</h2>

      {error && (
        <p className="text-sm text-destructive">{error}</p>
      )}

      {uploads.length === 0 && !error && (
        <p className="text-sm text-muted-foreground">Nog geen uploads.</p>
      )}

      {uploads.length > 0 && (
        <div className="space-y-2">
          {uploads.map((upload) => (
            <div
              key={upload.upload_id}
              className="rounded-lg border bg-card p-4 flex items-center justify-between gap-4"
            >
              <div className="min-w-0 flex-1 space-y-1">
                <p className="truncate text-sm font-medium">{upload.filename}</p>
                <p className="truncate text-xs text-muted-foreground">
                  {formatDate(upload.created_at)}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-3">
                {upload.total_jobs > 0 && (
                  <span className="text-xs text-muted-foreground">
                    {upload.completed}/{upload.total_jobs} pagina&apos;s
                  </span>
                )}
                <span
                  className={`rounded-full px-2 py-1 text-[11px] font-medium ${statusBadgeClasses(upload.final_status)}`}
                >
                  {statusLabel(upload.final_status)}
                </span>
                {upload.final_status === "processing" && (
                  <button
                    type="button"
                    onClick={() => handleCancel(upload.upload_id)}
                    disabled={cancelingIds.has(upload.upload_id)}
                    className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50"
                    aria-label="Upload annuleren"
                  >
                    {cancelingIds.has(upload.upload_id) ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Ban className="h-4 w-4" />
                    )}
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => handleDismiss(upload.upload_id)}
                  className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                  aria-label="Verbergen uit lijst"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
