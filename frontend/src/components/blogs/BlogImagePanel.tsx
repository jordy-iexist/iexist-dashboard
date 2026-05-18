"use client"

import { useCallback, useEffect, useMemo, useState, useTransition } from "react"

import { Button } from "@/components/ui/button"
import {
  BlogImage,
  BlogImageGenerationStatus,
} from "@/lib/wordpress-types"

type ImagesResponse =
  | {
      images: BlogImage[]
    }
  | {
      error: string
    }

type GenerationStatusResponse =
  | BlogImageGenerationStatus
  | {
      error: string
    }

type GenerateResponse =
  | {
      status: "queued"
      message: string
      job_id: string
    }
  | {
      error: string
    }

type ImageResponse =
  | BlogImage
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

function sourceLabel(source: BlogImage["source"]) {
  return source === "manual_upload" ? "Handmatige upload" : "Automatisch"
}

function formatFileSize(bytes: number) {
  if (!Number.isFinite(bytes) || bytes <= 0) {
    return "-"
  }

  if (bytes < 1024 * 1024) {
    return `${Math.round(bytes / 1024)} KB`
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function statusTone(state: BlogImageGenerationStatus["state"] | null) {
  if (state === "completed") {
    return {
      bar: "bg-green-500",
      badge: "border-green-200 bg-green-50 text-green-700",
    }
  }
  if (state === "failed") {
    return {
      bar: "bg-red-500",
      badge: "border-red-200 bg-red-50 text-red-700",
    }
  }
  if (state === "processing" || state === "pending") {
    return {
      bar: "bg-blue-500",
      badge: "border-blue-200 bg-blue-50 text-blue-700",
    }
  }
  return {
    bar: "bg-zinc-400",
    badge: "border-zinc-200 bg-zinc-50 text-zinc-700",
  }
}

export function BlogImagePanel({ blogId }: { blogId: string }) {
  const [images, setImages] = useState<BlogImage[]>([])
  const [generationStatus, setGenerationStatus] =
    useState<BlogImageGenerationStatus | null>(null)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [feedback, setFeedback] = useState<{
    type: "success" | "error" | null
    message: string
  }>({ type: null, message: "" })
  const [isPending, startTransition] = useTransition()

  const primaryImage = useMemo(
    () => images.find((image) => image.is_primary) ?? images[0] ?? null,
    [images]
  )

  const isGenerationInFlight =
    generationStatus?.state === "pending" ||
    generationStatus?.state === "processing"

  const generationProgress = generationStatus?.progress_percent ?? 0
  const generationTone = statusTone(generationStatus?.state ?? null)

  const loadImages = useCallback(
    async (options?: { silent?: boolean }) => {
      if (!options?.silent) {
        setIsLoading(true)
      }
      try {
        const response = await fetch(`/api/blogs/${blogId}/images`, {
          method: "GET",
          cache: "no-store",
        })
        const payload = (await response.json().catch(() => null)) as
          | ImagesResponse
          | null
        if (!response.ok) {
          throw new Error(getErrorMessage(payload, "Kon afbeeldingen niet laden."))
        }

        const nextImages =
          payload && "images" in payload && Array.isArray(payload.images)
            ? payload.images
            : []
        setImages(nextImages)
      } catch (error) {
        setFeedback({
          type: "error",
          message:
            error instanceof Error
              ? error.message
              : "Kon afbeeldingen niet laden.",
        })
      } finally {
        if (!options?.silent) {
          setIsLoading(false)
        }
      }
    },
    [blogId]
  )

  const loadGenerationStatus = useCallback(async () => {
    const response = await fetch(`/api/blogs/${blogId}/images/generation-status`, {
      method: "GET",
      cache: "no-store",
    })
    const payload = (await response.json().catch(() => null)) as
      | GenerationStatusResponse
      | null

    if (!response.ok) {
      throw new Error(
        getErrorMessage(payload, "Kon generatie status niet ophalen.")
      )
    }

    if (payload && "state" in payload) {
      setGenerationStatus(payload)
      return
    }

    throw new Error("Onverwachte response bij generatie status.")
  }, [blogId])

  const refreshImageData = useCallback(
    async (options?: { silent?: boolean }) => {
      await Promise.all([
        loadImages(options),
        loadGenerationStatus(),
      ])
    },
    [loadGenerationStatus, loadImages]
  )

  useEffect(() => {
    refreshImageData().catch((error) => {
      setFeedback({
        type: "error",
        message:
          error instanceof Error
            ? error.message
            : "Kon afbeelding gegevens niet laden.",
      })
    })
  }, [refreshImageData])

  useEffect(() => {
    if (!isGenerationInFlight) {
      return
    }

    const interval = window.setInterval(() => {
      refreshImageData({ silent: true }).catch(() => {
        // silent polling errors; manual refresh button remains available
      })
    }, 3000)

    return () => {
      window.clearInterval(interval)
    }
  }, [isGenerationInFlight, refreshImageData])

  const uploadImage = () => {
    if (!selectedFile) {
      return
    }
    setFeedback({ type: null, message: "" })
    startTransition(async () => {
      try {
        const formData = new FormData()
        formData.append("file", selectedFile)

        const response = await fetch(`/api/blogs/${blogId}/images/upload`, {
          method: "POST",
          body: formData,
        })
        const payload = (await response.json().catch(() => null)) as
          | ImageResponse
          | null
        if (!response.ok) {
          throw new Error(getErrorMessage(payload, "Uploaden is mislukt."))
        }
        setSelectedFile(null)
        setFeedback({
          type: "success",
          message: "Afbeelding geüpload en als primaire afbeelding ingesteld.",
        })
        await refreshImageData()
      } catch (error) {
        setFeedback({
          type: "error",
          message: error instanceof Error ? error.message : "Uploaden is mislukt.",
        })
      }
    })
  }

  const generateImage = () => {
    setFeedback({ type: null, message: "" })
    startTransition(async () => {
      try {
        const response = await fetch(`/api/blogs/${blogId}/images/generate`, {
          method: "POST",
        })
        const payload = (await response.json().catch(() => null)) as
          | GenerateResponse
          | null
        if (!response.ok) {
          throw new Error(
            getErrorMessage(payload, "Automatische generatie is mislukt.")
          )
        }

        const message =
          payload && "status" in payload
            ? payload.message
            : "Automatische generatie staat in de wachtrij."
        setFeedback({
          type: "success",
          message,
        })
      } catch (error) {
        setFeedback({
          type: "error",
          message:
            error instanceof Error
              ? error.message
              : "Automatische generatie is mislukt.",
        })
      } finally {
        await refreshImageData()
      }
    })
  }

  return (
    <section className="space-y-4 rounded-lg border bg-card p-5">
      <div className="space-y-1">
        <h2 className="text-lg font-semibold">Afbeelding</h2>
        <p className="text-sm text-muted-foreground">
          Er wordt automatisch een afbeelding gegenereerd. Upload je zelf een
          afbeelding, dan is die leidend voor publicatie.
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

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-3 rounded-md border p-3">
          <p className="text-sm font-medium">Primaire afbeelding</p>

          <div
            className={`space-y-2 rounded-md border px-3 py-2 text-xs ${generationTone.badge}`}
          >
            <div className="flex items-center justify-between gap-3">
              <span className="font-medium">Generatie status</span>
              <span className="font-semibold">{generationProgress}%</span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-white/70">
              <div
                className={`h-full transition-all duration-300 ${generationTone.bar}`}
                style={{ width: `${generationProgress}%` }}
              />
            </div>
            <p>
              {generationStatus?.message ||
                "Nog geen automatische afbeelding generatie gestart."}
            </p>
          </div>

          {isLoading ? (
            <p className="text-sm text-muted-foreground">Afbeelding laden...</p>
          ) : !primaryImage ? (
            <p className="text-sm text-muted-foreground">
              Nog geen afbeelding beschikbaar.
            </p>
          ) : primaryImage.signed_url ? (
            // Signed URLs can point to dynamic remote hosts; plain <img> keeps preview robust.
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={primaryImage.signed_url}
              alt="Primaire blog afbeelding"
              className="h-auto w-full rounded-md border object-cover"
            />
          ) : (
            <p className="text-sm text-muted-foreground">
              Geen preview URL beschikbaar.
            </p>
          )}

          {primaryImage && (
            <div className="text-xs text-muted-foreground space-y-1">
              <p>Bron: {sourceLabel(primaryImage.source)}</p>
              <p>Grootte: {formatFileSize(primaryImage.file_size_bytes)}</p>
              <p>Aangemaakt: {formatDate(primaryImage.created_at)}</p>
            </div>
          )}
        </div>

        <div className="space-y-3 rounded-md border p-3">
          <p className="text-sm font-medium">Acties</p>
          <div className="space-y-2">
            <label className="text-xs font-medium">Upload afbeelding</label>
            <input
              type="file"
              accept="image/jpeg,image/png,image/webp"
              onChange={(event) => {
                const file = event.target.files?.[0] ?? null
                setSelectedFile(file)
              }}
              disabled={isPending}
              className="block w-full text-sm"
            />
            <Button
              onClick={uploadImage}
              disabled={isPending || !selectedFile}
              className="w-full"
            >
              {isPending ? "Uploaden..." : "Upload en vervang primaire afbeelding"}
            </Button>
          </div>

          <div className="space-y-2">
            <label className="text-xs font-medium">Automatisch genereren</label>
            <Button
              variant="outline"
              onClick={generateImage}
              disabled={isPending || isGenerationInFlight}
              className="w-full"
            >
              {isGenerationInFlight
                ? "Generatie bezig..."
                : isPending
                ? "Genereren..."
                : "Genereer nieuwe afbeelding"}
            </Button>
          </div>

          <Button
            variant="ghost"
            onClick={() => refreshImageData()}
            disabled={isPending}
            className="w-full"
          >
            Vernieuw afbeeldingen
          </Button>
        </div>
      </div>

      {images.length > 0 && (
        <div className="space-y-2">
          <p className="text-sm font-medium">Recente afbeeldingen</p>
          <div className="grid gap-2 md:grid-cols-2">
            {images.slice(0, 6).map((image) => (
              <article key={image.id} className="rounded-md border p-2 text-xs">
                <div className="flex items-center justify-between gap-2">
                  <span>{sourceLabel(image.source)}</span>
                  {image.is_primary && (
                    <span className="rounded-full bg-green-100 px-2 py-0.5 text-green-700">
                      Primair
                    </span>
                  )}
                </div>
                <p className="text-muted-foreground mt-1">
                  {formatDate(image.created_at)}
                </p>
              </article>
            ))}
          </div>
        </div>
      )}
    </section>
  )
}
