"use client"

import { useEffect, useMemo, useState } from "react"
import { Plus, Trash2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  DEFAULT_LANDING_PAGE_PROMPT_TEMPLATE,
  type LandingPageUploadResponse,
} from "@/lib/landing-page-types"
import { parsePromptFieldsFromTemplate } from "@/components/CsvUpload"
import { type CustomersResponse } from "@/lib/customer-types"

type ManualRow = {
  id: string
  fields: Record<string, string>
  customerWebsiteId: string
}

function makeEmptyRow(fields: string[]): ManualRow {
  return {
    id: crypto.randomUUID(),
    fields: Object.fromEntries(fields.map((field) => [field, ""])),
    customerWebsiteId: "",
  }
}

function syncRowsToFields(rows: ManualRow[], fields: string[]): ManualRow[] {
  return rows.map((row) => ({
    ...row,
    fields: Object.fromEntries(fields.map((field) => [field, row.fields[field] ?? ""])),
  }))
}

export function ManualLandingPageEntry({ onSuccess }: { onSuccess?: () => void }) {
  const [template, setTemplate] = useState(DEFAULT_LANDING_PAGE_PROMPT_TEMPLATE)
  const [rows, setRows] = useState<ManualRow[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<{ jobs_queued: number; skipped_rows: number } | null>(null)
  const [customers, setCustomers] = useState<{ id: string; name: string }[]>([])

  useEffect(() => {
    let cancelled = false
    fetch("/api/customers?active_only=true", { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : null))
      .then((payload: CustomersResponse | null) => {
        if (!cancelled && payload?.websites) {
          setCustomers(
            payload.websites.map(({ id, name }) => ({ id, name }))
          )
        }
      })
      .catch(() => {
        // Klant-select is optioneel; zonder lijst blijft de kolom leeg.
      })
    return () => {
      cancelled = true
    }
  }, [])

  const { fields, error: templateError } = useMemo(
    () => parsePromptFieldsFromTemplate(template),
    [template]
  )

  const syncedRows = useMemo(() => {
    if (rows.length === 0) return [makeEmptyRow(fields)]
    return syncRowsToFields(rows, fields)
  }, [fields, rows])

  const updateField = (rowId: string, field: string, value: string) => {
    setRows((prev) =>
      (prev.length === 0 ? syncedRows : prev).map((r) =>
        r.id === rowId ? { ...r, fields: { ...r.fields, [field]: value } } : r
      )
    )
  }

  const updateCustomer = (rowId: string, customerWebsiteId: string) => {
    setRows((prev) =>
      (prev.length === 0 ? syncedRows : prev).map((r) =>
        r.id === rowId ? { ...r, customerWebsiteId } : r
      )
    )
  }

  const addRow = () => {
    setRows((prev) => [...(prev.length === 0 ? syncedRows : prev), makeEmptyRow(fields)])
  }

  const removeRow = (rowId: string) => {
    setRows((prev) => {
      const base = prev.length === 0 ? syncedRows : prev
      const next = base.filter((r) => r.id !== rowId)
      return next.length === 0 ? [makeEmptyRow(fields)] : next
    })
  }

  const currentRows = syncedRows
  const canSubmit =
    !submitting &&
    !templateError &&
    fields.length > 0 &&
    currentRows.some((r) =>
      fields.every((field) => r.fields[field]?.trim())
    )

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!canSubmit) return

    setSubmitting(true)
    setError(null)
    setSuccess(null)

    const apiRows = currentRows.map((r) => ({
      ...r.fields,
      ...(r.customerWebsiteId
        ? { __customer_website_id: r.customerWebsiteId }
        : {}),
    }))

    try {
      const res = await fetch("/api/landing-pages/manual", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ template, rows: apiRows }),
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
      setRows([makeEmptyRow(fields)])
      onSuccess?.()
    } catch {
      setError("Er is een fout opgetreden. Probeer het opnieuw.")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <div className="space-y-2">
        <label className="text-sm font-medium" htmlFor="manual-landing-page-template">
          Prompt template
        </label>
        <p className="text-xs text-muted-foreground">
          Gebruik {"{"}<span className="font-mono">placeholders</span>{"}"} voor de velden die je per rij wil invullen.
        </p>
        <textarea
          id="manual-landing-page-template"
          value={template}
          onChange={(e) => {
            setTemplate(e.target.value)
            setRows([])
          }}
          rows={6}
          className="w-full rounded-lg border bg-background px-3 py-2 text-sm font-mono resize-y"
          disabled={submitting}
        />
        {templateError ? (
          <p className="text-xs text-red-600">{templateError}</p>
        ) : fields.length > 0 ? (
          <p className="text-xs text-muted-foreground">
            Velden: {fields.join(", ")}
          </p>
        ) : null}
      </div>

      {!templateError && fields.length > 0 && (
      <div className="space-y-3">
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="border-b bg-muted/50">
                <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground w-10">#</th>
                {fields.map((field) => (
                  <th key={field} className="px-3 py-2 text-left text-xs font-medium text-muted-foreground whitespace-nowrap min-w-[160px]">
                    {field}
                  </th>
                ))}
                <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground whitespace-nowrap">
                  Klant (optioneel)
                </th>
                <th className="w-8" />
              </tr>
            </thead>
            <tbody>
              {currentRows.map((row, rowIndex) => (
                <tr key={row.id} className="border-b last:border-0 hover:bg-muted/25">
                  <td className="px-3 py-2 text-xs text-muted-foreground">{rowIndex + 1}</td>
                  {fields.map((field) => (
                    <td key={field} className="px-2 py-1.5">
                      <input
                        type="text"
                        value={row.fields[field] ?? ""}
                        onChange={(e) => updateField(row.id, field, e.target.value)}
                        className="w-full min-w-[140px] rounded border border-transparent bg-transparent px-2 py-1 text-sm focus:border-input focus:bg-background focus:outline-none"
                        disabled={submitting}
                        placeholder={field === "lengte" ? "bijv. 1200" : field}
                      />
                    </td>
                  ))}
                  <td className="px-2 py-1.5">
                    <select
                      value={row.customerWebsiteId}
                      onChange={(e) => updateCustomer(row.id, e.target.value)}
                      className="w-full min-w-[140px] rounded border border-input bg-background px-2 py-1 text-sm focus:outline-none"
                      disabled={submitting}
                      aria-label="Klant"
                    >
                      <option value="">Geen klant</option>
                      {customers.map((customer) => (
                        <option key={customer.id} value={customer.id}>
                          {customer.name}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="px-2 py-1.5">
                    {currentRows.length > 1 && (
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
      )}

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
