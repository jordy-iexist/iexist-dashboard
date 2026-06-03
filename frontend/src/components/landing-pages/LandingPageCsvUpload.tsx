"use client"

import { useEffect, useMemo, useState } from "react"
import { FileText, Loader2, Upload, X } from "lucide-react"

import { type ColumnMapping, readCsvHeaders, reconcileColumnMapping } from "@/lib/csv-mapping"
import { parsePromptFieldsFromTemplate } from "@/components/CsvUpload"
import { DEFAULT_LANDING_PAGE_PROMPT_TEMPLATE } from "@/lib/landing-page-types"
import { Button } from "@/components/ui/button"

function toFieldId(input: string): string {
  return input
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
}

export function LandingPageCsvUpload() {
  const [file, setFile] = useState<File | null>(null)
  const [headers, setHeaders] = useState<string[]>([])
  const [promptTemplate, setPromptTemplate] = useState("")
  const [columnMapping, setColumnMapping] = useState<ColumnMapping>({})
  const [isUploading, setIsUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)

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

  const applyFile = async (selectedFile: File) => {
    if (!selectedFile.name.toLowerCase().endsWith(".csv")) {
      setUploadError("Bestand moet een CSV zijn.")
      return
    }

    const parsedHeaders = await readCsvHeaders(selectedFile)
    if (parsedHeaders.length === 0) {
      setUploadError("CSV bevat geen leesbare kolomnamen op de eerste rij.")
      return
    }

    setFile(selectedFile)
    setHeaders(parsedHeaders)
    setUploadError(null)
  }

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0]
    if (selectedFile) {
      void applyFile(selectedFile)
    }
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    const droppedFile = e.dataTransfer.files[0]
    if (droppedFile) {
      void applyFile(droppedFile)
    }
  }

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
  }

  const removeFile = () => {
    setFile(null)
    setHeaders([])
    setColumnMapping({})
    setUploadError(null)
  }

  const missingMappings = useMemo(
    () =>
      templateFieldNames.filter((field) => {
        const mapped = columnMapping[field]
        return !mapped || !headers.includes(mapped)
      }),
    [columnMapping, headers, templateFieldNames]
  )

  const canUpload =
    file !== null &&
    headers.length > 0 &&
    !templateError &&
    templateFieldNames.length > 0 &&
    missingMappings.length === 0 &&
    !isUploading

  const handleUpload = async () => {
    if (!file || !canUpload) return

    setUploadError(null)
    setIsUploading(true)

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
        setUploadError(message)
        return
      }

      setFile(null)
      setHeaders([])
      setColumnMapping({})
      setUploadError(null)
    } catch {
      setUploadError("Er is een fout opgetreden bij het uploaden.")
    } finally {
      setIsUploading(false)
    }
  }

  return (
    <div className="mx-auto w-full max-w-2xl space-y-4">
      <div className="space-y-3 rounded-lg border bg-card p-4">
        <h3 className="text-sm font-semibold">Prompt opbouw</h3>
        <p className="text-xs text-muted-foreground">
          Maak je eigen prompt. Alles tussen {"{"} en {"}"} wordt een mappingveld.
          Laat leeg om de standaardprompt te gebruiken.
        </p>
        <textarea
          value={promptTemplate}
          onChange={(e) => setPromptTemplate(e.target.value)}
          placeholder={DEFAULT_LANDING_PAGE_PROMPT_TEMPLATE}
          disabled={isUploading}
          rows={6}
          className="w-full rounded-md border bg-background px-3 py-2 text-sm leading-relaxed"
        />
        {templateError ? (
          <p className="text-xs text-red-600">{templateError}</p>
        ) : (
          <p className="break-words text-xs text-muted-foreground">
            Placeholders: {templateFieldNames.join(", ")}
          </p>
        )}
      </div>

      {headers.length > 0 && templateFieldNames.length > 0 && (
        <div className="space-y-4 rounded-lg border p-4">
          <div>
            <h3 className="text-sm font-semibold">Placeholder mapping</h3>
            <p className="mt-1 text-xs text-muted-foreground">
              Koppel elke placeholder aan de juiste CSV-kolom.
            </p>
          </div>

          <p className="break-words text-xs text-muted-foreground">
            Gevonden kolommen: {headers.join(", ")}
          </p>

          <div className="space-y-3">
            {templateFieldNames.map((field, index) => (
              <div
                key={field}
                className="grid gap-1 md:grid-cols-[1fr_1.5fr] md:items-start"
              >
                <label
                  htmlFor={`mapping-${toFieldId(field)}-${index}`}
                  className="text-sm font-medium"
                >
                  {field}
                  <span className="mt-1 block text-xs font-normal text-muted-foreground">
                    Placeholder: {"{"}
                    {field}
                    {"}"}
                  </span>
                </label>
                <select
                  id={`mapping-${toFieldId(field)}-${index}`}
                  value={columnMapping[field] ?? ""}
                  onChange={(e) =>
                    setColumnMapping((prev) => ({ ...prev, [field]: e.target.value }))
                  }
                  className="w-full rounded-lg border bg-background px-3 py-2 text-sm"
                  disabled={isUploading}
                >
                  <option value="">Kies CSV-kolom</option>
                  {headers.map((header) => (
                    <option key={`${field}-${header}`} value={header}>
                      {header}
                    </option>
                  ))}
                </select>
              </div>
            ))}
          </div>

          {missingMappings.length > 0 && (
            <p className="text-xs text-amber-700">
              Nog te koppelen: {missingMappings.join(", ")}
            </p>
          )}
        </div>
      )}

      {!file ? (
        <div
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          className="cursor-pointer rounded-lg border-2 border-dashed p-12 transition-colors hover:bg-muted/50"
          onClick={() => document.getElementById("lp-csv-input")?.click()}
        >
          <div className="flex flex-col items-center justify-center gap-4">
            <div className="rounded-full bg-muted p-4">
              <Upload className="h-8 w-8 text-muted-foreground" />
            </div>
            <div className="text-center">
              <p className="text-sm font-medium">
                Sleep een CSV bestand hierheen of klik om te selecteren
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                Ondersteunde formaten: .csv
              </p>
            </div>
            <input
              id="lp-csv-input"
              type="file"
              accept=".csv"
              className="hidden"
              onChange={handleFileChange}
            />
          </div>
        </div>
      ) : (
        <div className="flex items-center justify-between rounded-lg border bg-card p-4">
          <div className="flex min-w-0 items-center gap-4">
            <div className="shrink-0 rounded bg-muted p-2">
              <FileText className="h-6 w-6" />
            </div>
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{file.name}</p>
              <p className="text-xs text-muted-foreground">
                {(file.size / 1024).toFixed(2)} KB
              </p>
            </div>
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={removeFile}
            disabled={isUploading}
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
      )}

      {uploadError && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {uploadError}
        </div>
      )}

      <Button className="w-full" onClick={handleUpload} disabled={!canUpload}>
        {isUploading ? (
          <>
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            Uploaden...
          </>
        ) : (
          "Upload CSV"
        )}
      </Button>
    </div>
  )
}
