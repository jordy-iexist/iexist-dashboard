"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { FileText, Loader2, Upload, X } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  type ColumnMapping,
  readCsvHeaders,
  reconcileColumnMapping,
} from "@/lib/csv-mapping"

const DEFAULT_PROMPT_TEMPLATE =
  "Schrijf een blog van {woorden} woorden voor klant {klant}. " +
  "Gebruik ankertekst '{anker_1}' met URL '{anker_1_url}' en " +
  "ankertekst '{anker_2}' met URL '{anker_2_url}'. " +
  "Noem '{klant}' minimaal 4 keer op natuurlijke wijze. " +
  "Voeg titel en tussenkoppen toe."

const UPLOAD_PROGRESS_STORAGE_KEY = "csv_upload_progress_v1"

type UploadFinalStatus = "processing" | "completed" | "completed_with_errors" | "canceled"

type UploadProgress = {
  uploadId: string
  jobsCreated: number
  skippedRows: number
  completed: number
  failed: number
  processing: number
  pending: number
  canceled: number
  processed: number
  remaining: number
  imagesGenerated: number
  imagesTarget: number
  isDone: boolean
  finalStatus: UploadFinalStatus
}

type PromptFieldParseResult = {
  fields: string[]
  error: string | null
}

function parsePromptFieldsFromTemplate(template: string): PromptFieldParseResult {
  const openCount = (template.match(/\{/g) ?? []).length
  const closeCount = (template.match(/\}/g) ?? []).length
  if (openCount !== closeCount) {
    return {
      fields: [],
      error: "Prompt bevat ongeldige accolades. Controleer '{' en '}'.",
    }
  }

  const fields: string[] = []
  const seen = new Set<string>()
  const placeholderRegex = /\{([^{}]*)\}/g
  let match: RegExpExecArray | null

  while ((match = placeholderRegex.exec(template)) !== null) {
    const field = (match[1] || "").trim()
    if (!field) {
      return {
        fields: [],
        error: "Lege placeholder gevonden. Gebruik bijvoorbeeld {klant}.",
      }
    }

    if (seen.has(field)) {
      continue
    }

    fields.push(field)
    seen.add(field)
  }

  if (fields.length === 0) {
    return {
      fields: [],
      error:
        "Voeg minimaal één placeholder toe in je prompt, bijvoorbeeld {klant}.",
    }
  }

  return { fields, error: null }
}

function parseNonNegativeNumber(value: unknown): number | null {
  if (!Number.isFinite(value)) {
    return null
  }

  if (typeof value !== "number") {
    return null
  }

  if (value < 0) {
    return null
  }

  return Math.floor(value)
}

function parseFinalStatus(value: unknown): UploadFinalStatus | null {
  if (
    value === "processing" ||
    value === "completed" ||
    value === "completed_with_errors" ||
    value === "canceled"
  ) {
    return value
  }

  return null
}

function readErrorMessage(payload: unknown): string | null {
  if (!payload || typeof payload !== "object") {
    return null
  }

  const error = (payload as { error?: unknown }).error
  if (typeof error === "string" && error.trim().length > 0) {
    return error
  }

  return null
}

function buildProgressFromStatusPayload(
  uploadId: string,
  payload: unknown
): UploadProgress | null {
  if (!payload || typeof payload !== "object") {
    return null
  }

  const record = payload as Record<string, unknown>
  const totalJobs =
    parseNonNegativeNumber(record.jobs_created) ??
    parseNonNegativeNumber(record.total_jobs)
  if (totalJobs === null) {
    return null
  }

  const completed = parseNonNegativeNumber(record.completed) ?? 0
  const failed = parseNonNegativeNumber(record.failed) ?? 0
  const processing = parseNonNegativeNumber(record.processing) ?? 0
  const canceled = parseNonNegativeNumber(record.canceled) ?? 0
  const pending = parseNonNegativeNumber(record.pending)
  const processed =
    parseNonNegativeNumber(record.processed) ??
    Math.min(completed + failed, totalJobs)
  const remaining =
    parseNonNegativeNumber(record.remaining) ??
    Math.max(totalJobs - processed, 0)
  const skippedRows = parseNonNegativeNumber(record.skipped_rows) ?? 0
  const imagesGenerated = parseNonNegativeNumber(record.images_generated) ?? 0
  const imagesTarget =
    parseNonNegativeNumber(record.images_target) ?? totalJobs
  const isDone =
    typeof record.is_done === "boolean" ? record.is_done : processed >= totalJobs
  const finalStatus =
    parseFinalStatus(record.final_status) ??
    (isDone
      ? failed > 0
        ? "completed_with_errors"
        : "completed"
      : "processing")

  return {
    uploadId,
    jobsCreated: totalJobs,
    skippedRows,
    completed,
    failed,
    processing,
    pending:
      pending ?? Math.max(totalJobs - completed - failed - processing, 0),
    canceled,
    processed,
    remaining,
    imagesGenerated: Math.min(imagesGenerated, imagesTarget),
    imagesTarget,
    isDone,
    finalStatus,
  }
}

function parseStoredUploadProgress(payload: unknown): UploadProgress | null {
  if (!payload || typeof payload !== "object") {
    return null
  }

  const record = payload as Record<string, unknown>
  const uploadId =
    typeof record.uploadId === "string" ? record.uploadId.trim() : ""
  if (!uploadId) {
    return null
  }

  const jobsCreated = parseNonNegativeNumber(record.jobsCreated)
  const completed = parseNonNegativeNumber(record.completed)
  const failed = parseNonNegativeNumber(record.failed)
  const processing = parseNonNegativeNumber(record.processing)
  const canceled = parseNonNegativeNumber(record.canceled) ?? 0
  const pending = parseNonNegativeNumber(record.pending)
  const processed = parseNonNegativeNumber(record.processed)
  const remaining = parseNonNegativeNumber(record.remaining)
  const skippedRows = parseNonNegativeNumber(record.skippedRows)
  const imagesGenerated = parseNonNegativeNumber(record.imagesGenerated)
  const imagesTarget = parseNonNegativeNumber(record.imagesTarget)
  const finalStatus = parseFinalStatus(record.finalStatus)
  const isDone = typeof record.isDone === "boolean" ? record.isDone : null

  if (
    jobsCreated === null ||
    completed === null ||
    failed === null ||
    processing === null ||
    pending === null ||
    processed === null ||
    remaining === null ||
    skippedRows === null ||
    finalStatus === null ||
    isDone === null
  ) {
    return null
  }

  return {
    uploadId,
    jobsCreated,
    completed,
    failed,
    processing,
    pending,
    canceled,
    processed,
    remaining,
    skippedRows,
    imagesGenerated:
      imagesGenerated === null ? 0 : Math.min(imagesGenerated, imagesTarget ?? jobsCreated),
    imagesTarget: imagesTarget === null ? jobsCreated : imagesTarget,
    finalStatus,
    isDone,
  }
}

function toFieldId(input: string): string {
  return input
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
}

export function CsvUpload() {
  const [file, setFile] = useState<File | null>(null)
  const [headers, setHeaders] = useState<string[]>([])
  const [promptTemplate, setPromptTemplate] = useState("")
  const [columnMapping, setColumnMapping] = useState<ColumnMapping>({})
  const [imageGenerationColumn, setImageGenerationColumn] = useState("")
  const [isUploading, setIsUploading] = useState(false)
  const [status, setStatus] = useState<{
    type: "success" | "error" | null
    message: string
  }>({ type: null, message: "" })
  const [uploadProgress, setUploadProgress] = useState<UploadProgress | null>(
    null
  )
  const [progressError, setProgressError] = useState<string | null>(null)
  const [isCanceling, setIsCanceling] = useState(false)
  const statusRequestInFlight = useRef(false)
  const [isProgressStorageReady, setIsProgressStorageReady] = useState(false)

  const effectivePromptTemplate = useMemo(
    () => (promptTemplate.trim() ? promptTemplate : DEFAULT_PROMPT_TEMPLATE),
    [promptTemplate]
  )

  const parsedTemplate = useMemo(
    () => parsePromptFieldsFromTemplate(effectivePromptTemplate),
    [effectivePromptTemplate]
  )
  const templateFieldNames = parsedTemplate.fields
  const templateError = parsedTemplate.error

  useEffect(() => {
    setColumnMapping((previousMapping) =>
      reconcileColumnMapping(headers, templateFieldNames, previousMapping)
    )
  }, [headers, templateFieldNames])

  useEffect(() => {
    setImageGenerationColumn((currentColumn) => {
      if (currentColumn && headers.includes(currentColumn)) {
        return currentColumn
      }
      return ""
    })
  }, [headers])

  const missingMappings = useMemo(
    () =>
      templateFieldNames.filter((field) => {
        const mapped = columnMapping[field]
        return typeof mapped !== "string" || mapped.trim().length === 0
      }),
    [columnMapping, templateFieldNames]
  )

  const progressPercentage = useMemo(() => {
    if (!uploadProgress || uploadProgress.jobsCreated <= 0) {
      return 0
    }

    return Math.min(
      100,
      Math.round((uploadProgress.processed / uploadProgress.jobsCreated) * 100)
    )
  }, [uploadProgress])

  const progressStateLabel = useMemo(() => {
    if (!uploadProgress) {
      return ""
    }

    if (uploadProgress.finalStatus === "completed_with_errors") {
      return "Klaar met fouten"
    }

    if (uploadProgress.finalStatus === "completed") {
      return "Klaar"
    }

    if (uploadProgress.finalStatus === "canceled") {
      return "Geannuleerd"
    }

    return "Bezig"
  }, [uploadProgress])

  useEffect(() => {
    try {
      const rawProgress = localStorage.getItem(UPLOAD_PROGRESS_STORAGE_KEY)
      if (!rawProgress) {
        return
      }

      const parsedProgress = parseStoredUploadProgress(JSON.parse(rawProgress))
      if (parsedProgress) {
        setUploadProgress(parsedProgress)
      } else {
        localStorage.removeItem(UPLOAD_PROGRESS_STORAGE_KEY)
      }
    } catch {
      localStorage.removeItem(UPLOAD_PROGRESS_STORAGE_KEY)
    } finally {
      setIsProgressStorageReady(true)
    }
  }, [])

  useEffect(() => {
    if (!isProgressStorageReady) {
      return
    }

    if (!uploadProgress) {
      localStorage.removeItem(UPLOAD_PROGRESS_STORAGE_KEY)
      return
    }

    localStorage.setItem(UPLOAD_PROGRESS_STORAGE_KEY, JSON.stringify(uploadProgress))
  }, [isProgressStorageReady, uploadProgress])

  const applyFile = async (selectedFile: File) => {
    if (
      selectedFile.type !== "text/csv" &&
      !selectedFile.name.toLowerCase().endsWith(".csv")
    ) {
      setStatus({
        type: "error",
        message: "Alleen CSV bestanden zijn toegestaan",
      })
      return
    }

    try {
      const detectedHeaders = await readCsvHeaders(selectedFile)
      if (detectedHeaders.length === 0) {
        setStatus({
          type: "error",
          message: "CSV bevat geen leesbare kolomnamen op de eerste rij",
        })
        return
      }

      setFile(selectedFile)
      setHeaders(detectedHeaders)
      setStatus({ type: null, message: "" })
    } catch {
      setStatus({
        type: "error",
        message: "CSV kolommen konden niet worden gelezen",
      })
    }
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
    setImageGenerationColumn("")
    setStatus({ type: null, message: "" })
  }

  const handleUpload = async () => {
    if (!file) {
      return
    }

    if (templateError) {
      setStatus({ type: "error", message: templateError })
      return
    }

    if (templateFieldNames.length === 0) {
      setStatus({
        type: "error",
        message: "Voeg minimaal één placeholder toe, bijvoorbeeld {klant}.",
      })
      return
    }

    if (missingMappings.length > 0) {
      setStatus({
        type: "error",
        message: `Kies een CSV-kolom voor: ${missingMappings.join(", ")}`,
      })
      return
    }

    setIsUploading(true)
    setStatus({ type: null, message: "" })
    setProgressError(null)

    const formData = new FormData()
    formData.append("file", file)
    formData.append("mapping", JSON.stringify(columnMapping))
    formData.append("template", promptTemplate)
    formData.append("image_generation_column", imageGenerationColumn)

    try {
      const response = await fetch("/api/csv/upload", {
        method: "POST",
        body: formData,
      })
      const payload = await response.json().catch(() => null)

      if (!response.ok) {
        throw new Error(readErrorMessage(payload) || "Upload mislukt")
      }

      const payloadRecord =
        payload && typeof payload === "object"
          ? (payload as Record<string, unknown>)
          : null
      const uploadId =
        payloadRecord && typeof payloadRecord.upload_id === "string"
          ? payloadRecord.upload_id
          : null
      const jobsQueued = parseNonNegativeNumber(payloadRecord?.jobs_queued)
      const skippedRows = parseNonNegativeNumber(payloadRecord?.skipped_rows) ?? 0
      const imagesTarget = parseNonNegativeNumber(payloadRecord?.images_target)
      setStatus({
        type: "success",
        message:
          jobsQueued !== null
            ? skippedRows > 0
              ? `Upload gestart. ${jobsQueued} blogs worden verwerkt, ${skippedRows} lege/incomplete rijen zijn overgeslagen.`
              : `Upload gestart. ${jobsQueued} blogs worden op de achtergrond verwerkt.`
            : "Upload gestart. Blogs worden op de achtergrond verwerkt.",
      })
      if (uploadId) {
        const jobsCreated = jobsQueued ?? 0
        setUploadProgress({
          uploadId,
          jobsCreated,
          skippedRows,
          completed: 0,
          failed: 0,
          processing: 0,
          pending: jobsCreated,
          canceled: 0,
          processed: 0,
          remaining: jobsCreated,
          imagesGenerated: 0,
          imagesTarget: imagesTarget ?? jobsCreated,
          isDone: jobsCreated === 0,
          finalStatus: jobsCreated === 0 ? "completed" : "processing",
        })
      } else {
        setUploadProgress(null)
      }
      setFile(null)
      setHeaders([])
      setColumnMapping({})
      setImageGenerationColumn("")
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : "Er is een fout opgetreden tijdens het uploaden"
      setStatus({
        type: "error",
        message,
      })
    } finally {
      setIsUploading(false)
    }
  }

  const currentUploadId = uploadProgress?.uploadId ?? null
  const isCurrentUploadDone = uploadProgress?.isDone ?? true

  const dismissUploadProgress = () => {
    if (!uploadProgress?.isDone) {
      return
    }

    setUploadProgress(null)
    setProgressError(null)
  }

  const handleCancelUpload = async () => {
    if (!uploadProgress?.uploadId || uploadProgress.isDone) {
      return
    }
    const confirmed = window.confirm(
      "Weet je zeker dat je deze blog-generatie wilt annuleren? Voltooide blogs blijven bewaard."
    )
    if (!confirmed) {
      return
    }
    setIsCanceling(true)
    try {
      const response = await fetch(
        `/api/csv/uploads/${encodeURIComponent(uploadProgress.uploadId)}/cancel`,
        { method: "POST" }
      )
      if (!response.ok) {
        const payload = await response.json().catch(() => null)
        const message = readErrorMessage(payload) || "Annuleren mislukt."
        setProgressError(message)
        return
      }
      setUploadProgress((prev) =>
        prev
          ? { ...prev, isDone: true, finalStatus: "canceled", pending: 0, processing: 0, remaining: 0 }
          : prev
      )
      setProgressError(null)
    } catch {
      setProgressError("Verbinding mislukt tijdens annuleren.")
    } finally {
      setIsCanceling(false)
    }
  }

  useEffect(() => {
    if (!currentUploadId || isCurrentUploadDone) {
      return
    }

    let isCancelled = false

    const pollUploadStatus = async () => {
      if (statusRequestInFlight.current) {
        return
      }

      statusRequestInFlight.current = true
      try {
        const response = await fetch(
          `/api/csv/uploads/${encodeURIComponent(currentUploadId)}/status`,
          {
            method: "GET",
            cache: "no-store",
          }
        )
        const payload = await response.json().catch(() => null)
        if (!response.ok) {
          throw new Error(readErrorMessage(payload) || "Kon uploadstatus niet ophalen")
        }

        const nextProgress = buildProgressFromStatusPayload(
          currentUploadId,
          payload
        )
        if (!nextProgress) {
          throw new Error("Uploadstatus heeft een ongeldig formaat")
        }

        if (isCancelled) {
          return
        }

        setProgressError(null)
        setUploadProgress((previousProgress) => {
          if (
            !previousProgress ||
            previousProgress.uploadId !== currentUploadId
          ) {
            return previousProgress
          }

          return {
            ...nextProgress,
            skippedRows:
              nextProgress.skippedRows === 0 && previousProgress.skippedRows > 0
                ? previousProgress.skippedRows
                : nextProgress.skippedRows,
          }
        })
      } catch (error) {
        if (isCancelled) {
          return
        }

        const message =
          error instanceof Error
            ? error.message
            : "Kon uploadstatus niet ophalen"
        setProgressError(message)
      } finally {
        statusRequestInFlight.current = false
      }
    }

    void pollUploadStatus()
    const intervalId = setInterval(() => {
      void pollUploadStatus()
    }, 2000)

    return () => {
      isCancelled = true
      clearInterval(intervalId)
      statusRequestInFlight.current = false
    }
  }, [currentUploadId, isCurrentUploadDone])

  const canUpload =
    !!file &&
    !isUploading &&
    !templateError &&
    templateFieldNames.length > 0 &&
    missingMappings.length === 0

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
          onChange={(event) => setPromptTemplate(event.target.value)}
          placeholder={DEFAULT_PROMPT_TEMPLATE}
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
                  onChange={(event) => {
                    const value = event.target.value
                    setColumnMapping((previousMapping) => ({
                      ...previousMapping,
                      [field]: value,
                    }))
                  }}
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

      {headers.length > 0 && (
        <div className="space-y-3 rounded-lg border p-4">
          <div>
            <h3 className="text-sm font-semibold">
              Afbeelding per rij (optioneel)
            </h3>
            <p className="mt-1 text-xs text-muted-foreground">
              Kies een CSV-kolom met ja/nee. Leeg of null betekent geen
              afbeelding voor die rij.
            </p>
          </div>

          <select
            id="image-generation-column"
            value={imageGenerationColumn}
            onChange={(event) => setImageGenerationColumn(event.target.value)}
            className="w-full rounded-lg border bg-background px-3 py-2 text-sm"
            disabled={isUploading}
          >
            <option value="">Geen kolom gekozen (geen afbeeldingen genereren)</option>
            {headers.map((header) => (
              <option key={`image-column-${header}`} value={header}>
                {header}
              </option>
            ))}
          </select>
        </div>
      )}

      {!file ? (
        <div
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          className="cursor-pointer rounded-lg border-2 border-dashed p-12 transition-colors hover:bg-muted/50"
          onClick={() => document.getElementById("csv-input")?.click()}
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
              id="csv-input"
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

      {status.message && (
        <div
          className={`rounded-lg border p-4 text-sm ${
            status.type === "success"
              ? "border-green-200 bg-green-50 text-green-700"
              : "border-red-200 bg-red-50 text-red-700"
          }`}
        >
          {status.message}
        </div>
      )}

      {uploadProgress && (
        <div className="space-y-4 rounded-lg border bg-card p-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold">Verwerkingsvoortgang</h3>
            <div className="flex items-center gap-2">
              <span
                className={`rounded-full px-2 py-1 text-xs font-medium ${
                  uploadProgress.finalStatus === "completed_with_errors"
                    ? "bg-amber-100 text-amber-800"
                    : uploadProgress.finalStatus === "completed"
                    ? "bg-green-100 text-green-800"
                    : uploadProgress.finalStatus === "canceled"
                    ? "bg-red-100 text-red-800"
                    : "bg-blue-100 text-blue-800"
                }`}
              >
                {progressStateLabel}
              </span>
              {!uploadProgress.isDone && (
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 px-2 text-xs"
                  onClick={handleCancelUpload}
                  disabled={isCanceling}
                  aria-label="Annuleer blog-generatie"
                >
                  {isCanceling ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    "Annuleer"
                  )}
                </Button>
              )}
              {uploadProgress.isDone && (
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7"
                  onClick={dismissUploadProgress}
                  aria-label="Sluit verwerkingsvoortgang"
                >
                  <X className="h-4 w-4" />
                </Button>
              )}
            </div>
          </div>

          <p className="text-sm text-muted-foreground">
            Verwerkt: {uploadProgress.processed}/{uploadProgress.jobsCreated} jobs
          </p>

          <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-primary transition-all duration-300"
              style={{ width: `${progressPercentage}%` }}
            />
          </div>

          <div className="grid gap-2 text-xs text-muted-foreground sm:grid-cols-2">
            <p>Jobs aangemaakt: {uploadProgress.jobsCreated}</p>
            <p>Rijen overgeslagen: {uploadProgress.skippedRows}</p>
            <p>Nog te verwerken: {uploadProgress.remaining}</p>
            <p>In behandeling: {uploadProgress.processing}</p>
            <p>
              Afbeeldingen gegenereerd: {uploadProgress.imagesGenerated}/
              {uploadProgress.imagesTarget}
            </p>
            {uploadProgress.failed > 0 && <p>Mislukt: {uploadProgress.failed}</p>}
          </div>

          {progressError && (
            <p className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
              Status update mislukt: {progressError}
            </p>
          )}
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
