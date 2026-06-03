"use client"

import { useState } from "react"
import { Plus, Trash2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  LANDING_PAGE_FIELD_LABELS,
  LANDING_PAGE_FIELDS,
  type LandingPageField,
  type LandingPageUploadResponse,
} from "@/lib/landing-page-types"

type ManualRow = {
  id: string
  fields: Record<LandingPageField, string>
}

function makeEmptyRow(): ManualRow {
  return {
    id: crypto.randomUUID(),
    fields: Object.fromEntries(
      LANDING_PAGE_FIELDS.map((f) => [f, ""])
    ) as Record<LandingPageField, string>,
  }
}

export function ManualLandingPageEntry({ onSuccess }: { onSuccess?: () => void }) {
  const [rows, setRows] = useState<ManualRow[]>([makeEmptyRow()])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<{ jobs_queued: number; skipped_rows: number } | null>(null)

  const updateField = (rowId: string, field: LandingPageField, value: string) => {
    setRows((prev) =>
      prev.map((r) =>
        r.id === rowId ? { ...r, fields: { ...r.fields, [field]: value } } : r
      )
    )
  }

  const addRow = () => {
    setRows((prev) => [...prev, makeEmptyRow()])
  }

  const removeRow = (rowId: string) => {
    setRows((prev) => {
      const next = prev.filter((r) => r.id !== rowId)
      return next.length === 0 ? [makeEmptyRow()] : next
    })
  }

  const canSubmit =
    !submitting &&
    rows.some((r) =>
      LANDING_PAGE_FIELDS.every((f) => r.fields[f]?.trim())
    )

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!canSubmit) return

    setSubmitting(true)
    setError(null)
    setSuccess(null)

    const apiRows = rows.map((r) => ({ ...r.fields }))

    try {
      const res = await fetch("/api/landing-pages/manual", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rows: apiRows }),
      })

      const data = await res.json().catch(() => null)

      if (!res.ok) {
        const msg =
          data && typeof (data as { error?: string }).error === "string"
            ? (data as { error: string }).error
            : "Verwerken mislukt. Probeer het opnieuw."
        setError(msg)
        return
      }

      const payload = data as LandingPageUploadResponse
      setSuccess({ jobs_queued: payload.jobs_queued, skipped_rows: payload.skipped_rows ?? 0 })
      setRows([makeEmptyRow()])
      onSuccess?.()
    } catch {
      setError("Er is een fout opgetreden. Probeer het opnieuw.")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <div className="space-y-3">
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="border-b bg-muted/50">
                <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground w-10">#</th>
                {LANDING_PAGE_FIELDS.map((field) => (
                  <th key={field} className="px-3 py-2 text-left text-xs font-medium text-muted-foreground whitespace-nowrap min-w-[160px]">
                    {LANDING_PAGE_FIELD_LABELS[field]}
                  </th>
                ))}
                <th className="w-8" />
              </tr>
            </thead>
            <tbody>
              {rows.map((row, rowIndex) => (
                <tr key={row.id} className="border-b last:border-0 hover:bg-muted/25">
                  <td className="px-3 py-2 text-xs text-muted-foreground">{rowIndex + 1}</td>
                  {LANDING_PAGE_FIELDS.map((field) => (
                    <td key={field} className="px-2 py-1.5">
                      <input
                        type="text"
                        value={row.fields[field]}
                        onChange={(e) => updateField(row.id, field, e.target.value)}
                        className="w-full min-w-[140px] rounded border border-transparent bg-transparent px-2 py-1 text-sm focus:border-input focus:bg-background focus:outline-none"
                        disabled={submitting}
                        placeholder={field === "lengte" ? "bijv. 1200" : LANDING_PAGE_FIELD_LABELS[field]}
                      />
                    </td>
                  ))}
                  <td className="px-2 py-1.5">
                    {rows.length > 1 && (
                      <button
                        type="button"
                        onClick={() => removeRow(row.id)}
                        className="text-muted-foreground hover:text-red-600 transition-colors"
                        aria-label="Rij verwijderen"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <button
          type="button"
          onClick={addRow}
          disabled={submitting}
          className="flex items-center gap-2 text-sm text-primary hover:underline disabled:opacity-50"
        >
          <Plus className="h-4 w-4" />
          Rij toevoegen
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {success && (
        <div className="rounded-lg border border-green-200 bg-green-50 p-3 text-sm text-green-700">
          Gelukt! {success.jobs_queued} landingspagina{success.jobs_queued === 1 ? "" : "'s"} worden verwerkt.
          {success.skipped_rows > 0 && ` ${success.skipped_rows} onvolledige rijen overgeslagen.`}
        </div>
      )}

      <Button type="submit" disabled={!canSubmit}>
        {submitting ? "Verwerken..." : "Genereren"}
      </Button>
    </form>
  )
}
