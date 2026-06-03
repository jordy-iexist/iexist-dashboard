"use client"

import { useRef, useState } from "react"

import { type LandingPageUploadResponse } from "@/lib/landing-page-types"

export function LandingPageCsvUpload() {
  const [file, setFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<{ jobs_queued: number } | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (!file) return

    setError(null)
    setSuccess(null)
    setUploading(true)

    try {
      const formData = new FormData()
      formData.append("file", file)

      const res = await fetch("/api/landing-pages/upload", {
        method: "POST",
        body: formData,
      })

      const data = await res.json().catch(() => null)

      if (!res.ok) {
        const message =
          data && typeof (data as { error?: string }).error === "string"
            ? (data as { error: string }).error
            : "Upload mislukt. Probeer het opnieuw."
        setError(message)
        return
      }

      const payload = data as LandingPageUploadResponse
      setSuccess({ jobs_queued: payload.jobs_queued })
      setFile(null)
      if (fileInputRef.current) {
        fileInputRef.current.value = ""
      }
    } catch {
      setError("Er is een fout opgetreden bij het uploaden.")
    } finally {
      setUploading(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <div className="space-y-2">
        <label className="text-sm font-medium" htmlFor="csv-file">
          CSV bestand
        </label>
        <input
          ref={fileInputRef}
          id="csv-file"
          type="file"
          accept=".csv"
          required
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null)
            setError(null)
            setSuccess(null)
          }}
          className="block w-full text-sm text-muted-foreground file:mr-4 file:rounded-md file:border file:border-input file:bg-background file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-foreground hover:file:bg-muted"
        />
        <div className="rounded-md border bg-muted/40 p-3 text-xs text-muted-foreground space-y-1">
          <p className="font-medium text-foreground">Vereiste kolommen:</p>
          <ul className="list-disc list-inside space-y-0.5">
            <li><code>website</code></li>
            <li><code>onderwerp</code></li>
            <li><code>lengte</code></li>
            <li><code>primaire_zoekwoorden</code></li>
            <li><code>secundaire_zoekwoorden</code></li>
          </ul>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {success && (
        <div className="rounded-lg border border-green-200 bg-green-50 p-3 text-sm text-green-700">
          Upload gelukt! {success.jobs_queued} landingspagina
          {success.jobs_queued === 1 ? "" : "'s"} in de wachtrij gezet.
        </div>
      )}

      <button
        type="submit"
        disabled={uploading || !file}
        className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {uploading ? "Uploaden..." : "Uploaden"}
      </button>
    </form>
  )
}
