"use client"

import { useEffect, useMemo, useRef, useState } from "react"

import { type ColumnMapping, readCsvHeaders, reconcileColumnMapping } from "@/lib/csv-mapping"
import { parsePromptFieldsFromTemplate } from "@/components/CsvUpload"
import { DEFAULT_LANDING_PAGE_PROMPT_TEMPLATE, type LandingPageUploadResponse } from "@/lib/landing-page-types"

function toFieldId(field: string): string {
  return field.replace(/[^a-zA-Z0-9_-]/g, "-")
}

export function LandingPageCsvUpload() {
  const [file, setFile] = useState<File | null>(null)
  const [headers, setHeaders] = useState<string[]>([])
  const [promptTemplate, setPromptTemplate] = useState("")
  const [columnMapping, setColumnMapping] = useState<ColumnMapping>({})
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<{ jobs_queued: number } | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const effectivePromptTemplate = useMemo(
    () => (promptTemplate.trim() ? promptTemplate : DEFAULT_LANDING_PAGE_PROMPT_TEMPLATE),
    [promptTemplate]
  )
  const parsedTemplate = useMemo(
    () => parsePromptFieldsFromTemplate(effectivePromptTemplate),
    [effectivePromptTemplate]
  )
  const templateFieldNames = parsedTemplate.fields
  const templateError = parsedTemplate.error

  useEffect(() => {
    setColumnMapping((prev) => reconcileColumnMapping(headers, templateFieldNames, prev))
  }, [headers, templateFieldNames])

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

  const missingMappings = useMemo(
    () =>
      templateFieldNames.filter((field) => {
        const mapped = columnMapping[field]
        return !mapped || !headers.includes(mapped)
      }),
    [columnMapping, headers, templateFieldNames]
  )
  const canSubmit =
    file !== null &&
    headers.length > 0 &&
    !templateError &&
    templateFieldNames.length > 0 &&
    missingMappings.length === 0 &&
    !uploading

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
      formData.append("template", promptTemplate)

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
      setColumnMapping({})
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
        <label className="text-sm font-medium" htmlFor="landing-page-template">
          Prompt template
        </label>
        <p className="text-xs text-muted-foreground">
          Maak je eigen prompt. Alles tussen {"{"} en {"}"} wordt een mappingveld.
          Laat leeg om de standaardprompt te gebruiken.
        </p>
        <textarea
          id="landing-page-template"
          value={promptTemplate}
          onChange={(e) => setPromptTemplate(e.target.value)}
          placeholder={DEFAULT_LANDING_PAGE_PROMPT_TEMPLATE}
          rows={6}
          className="w-full rounded-lg border bg-background px-3 py-2 text-sm font-mono resize-y"
          disabled={uploading}
        />
        {templateError ? (
          <p className="text-xs text-red-600">{templateError}</p>
        ) : templateFieldNames.length > 0 ? (
          <p className="text-xs text-muted-foreground">
            Placeholders: {templateFieldNames.join(", ")}
          </p>
        ) : null}
      </div>

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

      {headers.length > 0 && templateFieldNames.length > 0 && (
        <div className="space-y-3">
          <div>
            <p className="text-sm font-medium">Placeholder mapping</p>
            <p className="text-xs text-muted-foreground mt-0.5">
              Gevonden kolommen: {headers.join(", ")}
            </p>
          </div>
          <div className="rounded-md border divide-y">
            {templateFieldNames.map((field, index) => (
              <div key={`${field}-${index}`} className="flex items-center gap-3 px-3 py-2">
                <label
                  htmlFor={`mapping-${toFieldId(field)}-${index}`}
                  className="w-48 shrink-0 text-sm font-medium"
                >
                  {field}
                </label>
                <select
                  id={`mapping-${toFieldId(field)}-${index}`}
                  value={columnMapping[field] ?? ""}
                  onChange={(e) =>
                    setColumnMapping((prev) => ({ ...prev, [field]: e.target.value }))
                  }
                  className="flex-1 rounded-md border border-input bg-background px-2 py-1 text-sm"
                >
                  <option value="">— Kies een kolom —</option>
                  {headers.map((header, i) => (
                    <option key={`${header}-${i}`} value={header}>
                      {header}
                    </option>
                  ))}
                </select>
              </div>
            ))}
          </div>
          {missingMappings.length > 0 && (
            <p className="text-xs text-muted-foreground">
              Koppel nog: {missingMappings.join(", ")}
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
