"use client"

import { useCallback, useEffect, useState, useTransition } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { type CustomerWebsiteItem, type CustomersResponse } from "@/lib/customer-types"

type Feedback = {
  type: "success" | "error" | null
  message: string
}

type ErrorResponse = {
  error?: string
}

function getErrorMessage(payload: ErrorResponse | null, fallback: string): string {
  return payload?.error?.trim() ? payload.error : fallback
}

export function KlantenManager() {
  const [customers, setCustomers] = useState<CustomerWebsiteItem[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [feedback, setFeedback] = useState<Feedback>({ type: null, message: "" })
  const [createForm, setCreateForm] = useState({ name: "", baseUrl: "" })
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editForm, setEditForm] = useState({ name: "", baseUrl: "" })
  const [isPending, startTransition] = useTransition()

  const loadCustomers = useCallback(async () => {
    setIsLoading(true)
    try {
      const response = await fetch("/api/customers", { cache: "no-store" })
      const payload = (await response.json().catch(() => null)) as
        | (CustomersResponse & ErrorResponse)
        | null
      if (!response.ok) {
        throw new Error(getErrorMessage(payload, "Kon klanten niet ophalen."))
      }
      setCustomers(payload?.websites ?? [])
    } catch (error) {
      setFeedback({
        type: "error",
        message:
          error instanceof Error ? error.message : "Kon klanten niet ophalen.",
      })
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadCustomers()
  }, [loadCustomers])

  const addCustomer = () => {
    setFeedback({ type: null, message: "" })
    startTransition(async () => {
      try {
        const response = await fetch("/api/customers", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: createForm.name.trim(),
            base_url: createForm.baseUrl.trim(),
          }),
        })
        const payload = (await response.json().catch(() => null)) as ErrorResponse | null
        if (!response.ok) {
          throw new Error(getErrorMessage(payload, "Kon klant niet toevoegen."))
        }
        setCreateForm({ name: "", baseUrl: "" })
        setFeedback({ type: "success", message: "Klant is toegevoegd." })
        await loadCustomers()
      } catch (error) {
        setFeedback({
          type: "error",
          message:
            error instanceof Error ? error.message : "Kon klant niet toevoegen.",
        })
      }
    })
  }

  const startEditing = (customer: CustomerWebsiteItem) => {
    setEditingId(customer.id)
    setEditForm({ name: customer.name, baseUrl: customer.base_url })
  }

  const patchCustomer = (
    customerId: string,
    body: Record<string, unknown>,
    successMessage: string
  ) => {
    setFeedback({ type: null, message: "" })
    startTransition(async () => {
      try {
        const response = await fetch(
          `/api/customers/${encodeURIComponent(customerId)}`,
          {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          }
        )
        const payload = (await response.json().catch(() => null)) as ErrorResponse | null
        if (!response.ok) {
          throw new Error(getErrorMessage(payload, "Kon klant niet bijwerken."))
        }
        setEditingId(null)
        setFeedback({ type: "success", message: successMessage })
        await loadCustomers()
      } catch (error) {
        setFeedback({
          type: "error",
          message:
            error instanceof Error ? error.message : "Kon klant niet bijwerken.",
        })
      }
    })
  }

  const saveEdit = (customerId: string) => {
    patchCustomer(
      customerId,
      {
        name: editForm.name.trim(),
        base_url: editForm.baseUrl.trim(),
      },
      "Klant is bijgewerkt."
    )
  }

  const toggleActive = (customer: CustomerWebsiteItem) => {
    patchCustomer(
      customer.id,
      { is_active: !customer.is_active },
      customer.is_active ? "Klant is gedeactiveerd." : "Klant is geactiveerd."
    )
  }

  return (
    <div className="space-y-6">
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

      <div className="grid gap-6 lg:grid-cols-3">
        <section className="lg:col-span-1">
          <div className="rounded-lg border p-4 space-y-3">
            <h2 className="text-sm font-semibold">Nieuwe klant</h2>
            <Input
              placeholder="Naam (bijv. Klant A)"
              value={createForm.name}
              onChange={(event) =>
                setCreateForm((current) => ({
                  ...current,
                  name: event.target.value,
                }))
              }
              disabled={isPending}
            />
            <Input
              placeholder="https://voorbeeld.nl"
              value={createForm.baseUrl}
              onChange={(event) =>
                setCreateForm((current) => ({
                  ...current,
                  baseUrl: event.target.value,
                }))
              }
              disabled={isPending}
            />
            <Button
              onClick={addCustomer}
              disabled={
                isPending ||
                createForm.name.trim().length === 0 ||
                createForm.baseUrl.trim().length === 0
              }
              className="w-full"
            >
              Klant toevoegen
            </Button>
          </div>
        </section>

        <section className="lg:col-span-2">
          <div className="rounded-lg border p-4 space-y-3">
            <h2 className="text-sm font-semibold">Alle klanten</h2>
            {isLoading ? (
              <p className="text-sm text-muted-foreground">Klanten laden...</p>
            ) : customers.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Nog geen klanten toegevoegd.
              </p>
            ) : (
              <div className="space-y-2">
                {customers.map((customer) => (
                  <div
                    key={customer.id}
                    className="rounded-md border px-3 py-2 text-sm"
                  >
                    {editingId === customer.id ? (
                      <div className="space-y-2">
                        <Input
                          value={editForm.name}
                          onChange={(event) =>
                            setEditForm((current) => ({
                              ...current,
                              name: event.target.value,
                            }))
                          }
                          disabled={isPending}
                        />
                        <Input
                          value={editForm.baseUrl}
                          onChange={(event) =>
                            setEditForm((current) => ({
                              ...current,
                              baseUrl: event.target.value,
                            }))
                          }
                          disabled={isPending}
                        />
                        <div className="flex gap-2">
                          <Button
                            size="sm"
                            onClick={() => saveEdit(customer.id)}
                            disabled={
                              isPending ||
                              editForm.name.trim().length === 0 ||
                              editForm.baseUrl.trim().length === 0
                            }
                          >
                            Opslaan
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => setEditingId(null)}
                            disabled={isPending}
                          >
                            Annuleren
                          </Button>
                        </div>
                      </div>
                    ) : (
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div>
                          <p className="font-medium">{customer.name}</p>
                          <p className="text-xs text-muted-foreground truncate">
                            {customer.domain}
                          </p>
                          {!customer.is_active && (
                            <p className="text-[11px] text-amber-600 mt-1">
                              Gedeactiveerd
                            </p>
                          )}
                        </div>
                        <div className="flex gap-2">
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => startEditing(customer)}
                            disabled={isPending}
                          >
                            Bewerken
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => toggleActive(customer)}
                            disabled={isPending}
                          >
                            {customer.is_active ? "Deactiveren" : "Activeren"}
                          </Button>
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  )
}
