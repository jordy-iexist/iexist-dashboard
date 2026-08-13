"use client"

import Link from "next/link"
import { ChevronRight, CircleAlert, CircleCheck } from "lucide-react"
import { useCallback, useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { type CustomerWebsiteListItem, type CustomersResponse } from "@/lib/customer-types"

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

function PlacementBadge({
  placed,
  target,
}: {
  placed: number
  target: number | null
}) {
  if (typeof target !== "number") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-1 text-[11px] font-medium text-muted-foreground">
        {placed} / —
      </span>
    )
  }

  const remaining = Math.max(target - placed, 0)
  const isOnTrack = remaining === 0

  return (
    <span
      title={
        isOnTrack
          ? "Doel deze maand behaald."
          : `Nog ${remaining} blog${remaining === 1 ? "" : "s"} te plaatsen deze maand.`
      }
      className={`inline-flex items-center gap-1 rounded-full px-2 py-1 text-[11px] font-medium ${
        isOnTrack
          ? "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300"
          : "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300"
      }`}
    >
      {isOnTrack ? (
        <CircleCheck className="size-3" />
      ) : (
        <CircleAlert className="size-3" />
      )}
      {placed} / {target}
    </span>
  )
}

export function KlantenManager() {
  const [customers, setCustomers] = useState<CustomerWebsiteListItem[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [feedback, setFeedback] = useState<Feedback>({ type: null, message: "" })

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

      <div className="space-y-3">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold">Alle klanten</h2>
          <Button asChild size="sm">
            <Link href="/dashboard/klanten/nieuw">Klant toevoegen</Link>
          </Button>
        </div>

        {isLoading ? (
          <p className="text-sm text-muted-foreground">Klanten laden...</p>
        ) : customers.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Nog geen klanten toegevoegd.
          </p>
        ) : (
          <div className="space-y-2">
            {customers.map((customer) => (
              <Link
                key={customer.id}
                href={`/dashboard/klanten/${customer.id}`}
                className="flex items-center justify-between gap-2 rounded-lg bg-[#FAB806]/10 px-3 py-2 text-sm transition-colors hover:bg-[#FAB806]/20"
              >
                <div className="min-w-0">
                  <p className="font-medium">{customer.name}</p>
                  <p className="truncate text-xs text-muted-foreground">
                    {customer.domain}
                  </p>
                  {!customer.is_active && (
                    <p className="mt-1 text-[11px] text-amber-600">Gedeactiveerd</p>
                  )}
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <PlacementBadge
                    placed={customer.placed_this_month}
                    target={customer.target_blogs_per_month}
                  />
                  <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
