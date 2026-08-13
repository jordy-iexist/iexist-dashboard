"use client"

import Link from "next/link"
import { ChevronRight, CircleAlert, CircleCheck, Search } from "lucide-react"
import { useCallback, useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { CategoryManagerDialog } from "@/components/klanten/CategoryManagerDialog"
import {
  type CustomerCategory,
  type CustomerWebsiteListItem,
  type CustomersResponse,
} from "@/lib/customer-types"

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

function CategoryBadge({ name }: { name: string }) {
  return (
    <span className="inline-flex items-center rounded-full bg-muted px-2 py-1 text-[11px] font-medium text-muted-foreground">
      {name}
    </span>
  )
}

export function KlantenManager() {
  const [customers, setCustomers] = useState<CustomerWebsiteListItem[]>([])
  const [categories, setCategories] = useState<CustomerCategory[]>([])
  const [categoryFilter, setCategoryFilter] = useState("")
  const [searchQuery, setSearchQuery] = useState("")
  const [isLoading, setIsLoading] = useState(true)
  const [feedback, setFeedback] = useState<Feedback>({ type: null, message: "" })
  const [isCategoryDialogOpen, setIsCategoryDialogOpen] = useState(false)

  const loadCategories = useCallback(async () => {
    try {
      const response = await fetch("/api/customer-categories", { cache: "no-store" })
      if (!response.ok) return
      const payload = (await response.json().catch(() => null)) as
        | { categories?: CustomerCategory[] }
        | null
      setCategories(payload?.categories ?? [])
    } catch {
      // Filter list keeps its previous state; the manager dialog surfaces errors.
    }
  }, [])

  const loadCustomers = useCallback(async (category: string) => {
    setIsLoading(true)
    try {
      const params = new URLSearchParams()
      if (category) params.set("category_id", category)
      const query = params.toString()
      const response = await fetch(
        `/api/customers${query ? `?${query}` : ""}`,
        { cache: "no-store" }
      )
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
    void loadCategories()
  }, [loadCategories])

  useEffect(() => {
    void loadCustomers(categoryFilter)
  }, [loadCustomers, categoryFilter])

  const normalizedQuery = searchQuery.trim().toLowerCase()
  const visibleCustomers = normalizedQuery
    ? customers.filter(
        (customer) =>
          customer.name.toLowerCase().includes(normalizedQuery) ||
          customer.domain?.toLowerCase().includes(normalizedQuery)
      )
    : customers

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
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold">Alle klanten</h2>
          <div className="flex items-center gap-2">
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                type="search"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                placeholder="Zoek op klantnaam..."
                aria-label="Zoek op klantnaam"
                className="h-9 w-full pl-8 sm:w-56"
              />
            </div>
            <select
              value={categoryFilter}
              onChange={(event) => setCategoryFilter(event.target.value)}
              aria-label="Filter op categorie"
              className="h-9 rounded-md border border-input bg-background px-3 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              <option value="">Alle categorieën</option>
              <option value="none">Zonder categorie</option>
              {categories.map((category) => (
                <option key={category.id} value={category.id}>
                  {category.name}
                </option>
              ))}
            </select>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setIsCategoryDialogOpen(true)}
            >
              Categorieën
            </Button>
            <Button asChild size="sm">
              <Link href="/dashboard/klanten/nieuw">Klant toevoegen</Link>
            </Button>
          </div>
        </div>

        {isLoading ? (
          <p className="text-sm text-muted-foreground">Klanten laden...</p>
        ) : customers.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Nog geen klanten toegevoegd.
          </p>
        ) : visibleCustomers.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Geen klanten gevonden voor deze zoekopdracht.
          </p>
        ) : (
          <div className="space-y-2">
            {visibleCustomers.map((customer) => (
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
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  {customer.category_name && (
                    <CategoryBadge name={customer.category_name} />
                  )}
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

      <CategoryManagerDialog
        open={isCategoryDialogOpen}
        onOpenChange={setIsCategoryDialogOpen}
        onCategoriesChanged={() => {
          void loadCategories()
          void loadCustomers(categoryFilter)
        }}
      />
    </div>
  )
}
