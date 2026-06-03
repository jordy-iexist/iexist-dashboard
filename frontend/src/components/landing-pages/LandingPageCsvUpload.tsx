"use client"

import { useEffect, useRef, useState } from "react"

import { type ColumnMapping, readCsvHeaders, reconcileColumnMapping } from "@/lib/csv-mapping"
import { LANDING_PAGE_FIELDS, type LandingPageUploadResponse } from "@/lib/landing-page-types"

const FIELD_LABELS: Record<string, string> = {
  website: "Website",
  onderwerp: "Onderwerp",
  lengte: "Lengte (woorden)",
  primaire_zoekwoorden: "Primaire zoekwoorden",
  secundaire_zoekwoorden: "Secundaire zoekwoorden",
}

export function LandingPageCsvUpload() {
  const [file, setFile] = useState<File | null>(null)
  const [headers, setHeaders] = useState<string[]>([])
  const [columnMapping, setColumnMapping] = useState<ColumnMapping>({})
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<{ jobs_queued: number } | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    setColumnMapping((prev) => reconcileColumnMapping(headers, LANDING_PAGE_FIELDS, prev))
  }, [headers])

  const applyFile = async (selectedFile: File | null) => {
    setError(null)
    setSuccess(null)
    setFile(selectedFile)

    if (!selectedFile) {
      setHeaders([])
      return
    }

    if (!selectedFile.name.toLowerCase().endsWith(".csv")) {
      setError("Bestand moet een CSV zijn.")
      setHeaders([])
      return
    }

    const parsedHeaders = await readCsvHeaders(selectedFile)
    if (parsedHeaders.length === 0) {
      setError("CSV bevat geen leesbare kolomnamen op de eerste rij.")
      setHeaders([])
      return
    }

    setHeaders(parsedHeaders)
  }

  const missingMappings = LANDING_PAGE_FIELDS.filter((field) => !columnMapping[field])
  const canSubmit = file !== null && headers.length > 0 && missingMappings.length === 0 && !uploading

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (!file || !canSubmit) return

    setError(null)
    setSuccess(null)
    setUploading(true)

    try {
      const formData = new FormData()
      formData.append("file", file)
      formData.append("mapping", JSON.stringify(columnMapping))

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
      setHeaders([])
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
          onChange={(e) => applyFile(e.target.files?.[0] ?? null)}
          className="block w-full text-sm text-muted-foreground file:mr-4 file:rounded-md file:border file:border-input file:bg-background file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-foreground hover:file:bg-muted"
        />
      </div>

      {headers.length > 0 && (
        <div className="space-y-3">
          <div>
            <p className="text-sm font-medium">Koppel kolommen</p>
            <p className="text-xs text-muted-foreground mt-0.5">
              Gevonden kolommen: {headers.join(", ")}
            </p>
          </div>
          <div className="rounded-md border divide-y">
            {LANDING_PAGE_FIELDS.map((field) => (
              <div key={field} className="flex items-center gap-3 px-3 py-2">
                <label
                  htmlFor={`mapping-${field}`}
                  className="w-48 shrink-0 text-sm font-medium"
                >
                  {FIELD_LABELS[field]}
                </label>
                <select
                  id={`mapping-${field}`}
                  value={columnMapping[field] ?? ""}
                  onChange={(e) =>
                    setColumnMapping((prev) => ({ ...prev, [field]: e.target.value }))
                  }
                  className="flex-1 rounded-md border border-input bg-background px-2 py-1 text-sm"
                >
                  <option value="">— Kies een kolom —</option>
                  {headers.map((header) => (
                    <option key={header} value={header}>
                      {header}
                    </option>
                  ))}
                </select>
              </div>
            ))}
          </div>
          {missingMappings.length > 0 && (
            <p className="text-xs text-muted-foreground">
              Koppel nog: {missingMappings.map((f) => FIELD_LABELS[f]).join(", ")}
            </p>
          )}
        </div>
      )}

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
        disabled={!canSubmit}
        className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {uploading ? "Uploaden..." : "Uploaden"}
      </button>
    </form>
  )
}
