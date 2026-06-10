"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { useMemo, useState, useTransition } from "react"

import { type LandingPageListItem } from "@/lib/landing-page-types"

function formatDate(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return "-"
  return new Intl.DateTimeFormat("nl-NL", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date)
}

function statusBadgeClasses(status: string) {
  switch (status) {
    case "pending":
      return "bg-muted text-muted-foreground"
    case "processing":
      return "bg-amber-100 text-amber-800"
    case "completed":
      return "bg-green-100 text-green-800"
    case "failed":
      return "bg-red-100 text-red-800"
    default:
      return "bg-muted text-muted-foreground"
  }
}

function statusLabel(status: string) {
  switch (status) {
    case "pending":
      return "In wachtrij"
    case "processing":
      return "Bezig"
    case "completed":
      return "Voltooid"
    case "failed":
      return "Mislukt"
    default:
      return status
  }
}

function getErrorMessage(payload: unknown, fallback: string): string {
  if (
    payload &&
    typeof payload === "object" &&
    "error" in payload &&
    typeof (payload as { error: unknown }).error === "string"
  ) {
    return (payload as { error: string }).error
  }
  return fallback
}

export function LandingPagesBatchList({
  landingPages,
}: {
  landingPages: LandingPageListItem[]
}) {
  const router = useRouter()
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [feedback, setFeedback] = useState<{
    type: "success" | "error" | null
    message: string
  }>({ type: null, message: "" })
  const [isPending, startTransition] = useTransition()

  const ownedPages = useMemo(
    () => landingPages.filter((lp) => lp.is_owner !== false),
    [landingPages]
  )

  const allSelected = useMemo(
    () => ownedPages.length > 0 && selectedIds.length === ownedPages.length,
    [ownedPages.length, selectedIds.length]
  )

  const toggleSelection = (id: string, checked: boolean) => {
    setSelectedIds((current) => {
      if (checked) {
        return current.includes(id) ? current : [...current, id]
      }
      return current.filter((v) => v !== id)
    })
  }

  const toggleSelectAll = (checked: boolean) => {
    setSelectedIds(checked ? ownedPages.map((lp) => lp.id) : [])
  }

  const deleteBatch = () => {
    if (selectedIds.length === 0) return
    const confirmed = window.confirm(
      `Weet je zeker dat je ${selectedIds.length} landingspagina('s) wilt verwijderen? Dit kan niet ongedaan gemaakt worden.`
    )
    if (!confirmed) return

    setFeedback({ type: null, message: "" })
    startTransition(async () => {
      try {
        const response = await fetch("/api/landing-pages/delete/batch", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ landing_page_ids: selectedIds }),
        })
        const payload = (await response.json().catch(() => null)) as
          | { deleted: number; missing: string[]; error?: string }
          | null
        if (!response.ok) {
          throw new Error(getErrorMessage(payload, "Batch verwijderen is mislukt."))
        }
        setFeedback({
          type: "success",
          message: `${payload?.deleted ?? 0} landingspagina('s) verwijderd.`,
        })
        setSelectedIds([])
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

  return (
    <div className="space-y-4">
      {feedback.type && (
        <div
          className={`rounded-lg border p-3 text-sm ${
            feedback.type === "success"
              ? "border-green-200 bg-green-50 text-green-700"
              : "border-red-200 bg-red-50 text-red-700"
          }`}
        >
          {feedback.message}
        </div>
      )}

      <div className="rounded-lg border p-4 flex items-center gap-4">
        <label className="flex items-center gap-2 text-sm cursor-pointer select-none">
          <input
            type="checkbox"
            checked={allSelected}
            onChange={(e) => toggleSelectAll(e.target.checked)}
            className="rounded border-input"
          />
          Selecteer alles op deze pagina
        </label>

        {selectedIds.length > 0 && (
          <button
            type="button"
            onClick={deleteBatch}
            disabled={isPending}
            className="ml-auto rounded-md bg-destructive px-3 py-1.5 text-sm font-medium text-destructive-foreground hover:bg-destructive/90 disabled:opacity-50"
          >
            Verwijder selectie ({selectedIds.length})
          </button>
        )}
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {landingPages.map((item) => (
          <div
            key={item.id}
            className="rounded-lg border bg-card flex items-start gap-2 p-4"
          >
            {item.is_owner !== false && (
              <input
                type="checkbox"
                checked={selectedIds.includes(item.id)}
                onChange={(e) => toggleSelection(item.id, e.target.checked)}
                onClick={(e) => e.stopPropagation()}
                aria-label="Selecteer"
                className="mt-0.5 shrink-0 rounded border-input cursor-pointer"
              />
            )}
            <Link
              href={`/dashboard/landing-pages/${item.id}`}
              className="flex-1 min-w-0 space-y-2 hover:opacity-75 transition-opacity"
            >
              <div className="flex items-start justify-between gap-2">
                <p className="font-medium text-sm leading-snug line-clamp-2">
                  {item.onderwerp || "Onbekend onderwerp"}
                </p>
                <div className="flex shrink-0 items-center gap-1">
                  {item.is_owner === false && (
                    <span className="rounded-full bg-blue-100 px-2 py-0.5 text-[11px] font-medium text-blue-800">
                      Gedeeld met jou
                    </span>
                  )}
                  {item.is_owner !== false && item.is_public === true && (
                    <span className="rounded-full bg-blue-100 px-2 py-0.5 text-[11px] font-medium text-blue-800">
                      Gedeeld
                    </span>
                  )}
                  <span
                    className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${statusBadgeClasses(item.status)}`}
                  >
                    {statusLabel(item.status)}
                  </span>
                </div>
              </div>
              {item.meta_title && (
                <p className="text-xs text-muted-foreground line-clamp-1">
                  {item.meta_title}
                </p>
              )}
              <div className="text-xs text-muted-foreground space-y-0.5">
                <p className="truncate">{item.filename}</p>
                <p>{formatDate(item.created_at)}</p>
              </div>
            </Link>
          </div>
        ))}
      </div>
    </div>
  )
}
