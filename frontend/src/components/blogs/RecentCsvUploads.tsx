"use client"

import { useEffect, useRef, useState } from "react"
import { X } from "lucide-react"

import { Skeleton } from "@/components/ui/skeleton"

type FinalStatus = "processing" | "completed" | "completed_with_errors" | "canceled"

interface RecentUploadItem {
  upload_id: string
  filename: string
  template: string
  created_at: string
  total_jobs: number
  completed: number
  failed: number
  canceled: number
  processed: number
  is_done: boolean
  final_status: FinalStatus
}

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

export function RecentCsvUploads() {
  const [uploads, setUploads] = useState<RecentUploadItem[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const isFetchingRef = useRef(false)

  const handleDismiss = async (uploadId: string) => {
    const previous = uploads
    setUploads((prev) => prev.filter((u) => u.upload_id !== uploadId))
    try {
      const res = await fetch(`/api/csv/uploads/${uploadId}/dismiss`, { method: "POST" })
      if (!res.ok) {
        setUploads(previous)
        setError("Verbergen mislukt.")
      }
    } catch {
      setUploads(previous)
      setError("Verbergen mislukt.")
    }
  }

  const fetchUploads = async (initial = false) => {
    if (isFetchingRef.current) return
    isFetchingRef.current = true
    try {
      const res = await fetch("/api/csv/uploads", { cache: "no-store" })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        setError(body.error ?? "Uploads ophalen mislukt.")
        return
      }
      const data: { uploads: RecentUploadItem[] } = await res.json()
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
                  {upload.template} · {formatDate(upload.created_at)}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-3">
                {upload.total_jobs > 0 && (
                  <span className="text-xs text-muted-foreground">
                    {upload.completed}/{upload.total_jobs} blogs
                  </span>
                )}
                <span
                  className={`rounded-full px-2 py-1 text-[11px] font-medium ${statusBadgeClasses(upload.final_status)}`}
                >
                  {statusLabel(upload.final_status)}
                </span>
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
