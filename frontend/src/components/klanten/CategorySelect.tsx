"use client"

import { Plus } from "lucide-react"
import { useCallback, useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { CategoryManagerDialog } from "@/components/klanten/CategoryManagerDialog"
import { type CustomerCategory } from "@/lib/customer-types"

export function CategorySelect({
  value,
  onChange,
  disabled,
}: {
  value: string
  onChange: (value: string) => void
  disabled?: boolean
}) {
  const [categories, setCategories] = useState<CustomerCategory[]>([])
  const [isDialogOpen, setIsDialogOpen] = useState(false)

  const loadCategories = useCallback(async () => {
    try {
      const response = await fetch("/api/customer-categories", { cache: "no-store" })
      if (!response.ok) return
      const payload = (await response.json().catch(() => null)) as
        | { categories?: CustomerCategory[] }
        | null
      setCategories(payload?.categories ?? [])
    } catch {
      // Filter stays on its previous state if this fails; the manager dialog
      // surfaces its own errors when the user actually tries to manage categories.
    }
  }, [])

  useEffect(() => {
    // Standard fetch-on-mount pattern also used by CategoryManagerDialog and
    // KlantenManager — eslint's heuristic flags this instance but not those.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadCategories()
  }, [loadCategories])

  return (
    <>
      <div className="flex items-center gap-2">
        <select
          value={value}
          onChange={(event) => onChange(event.target.value)}
          disabled={disabled}
          className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
        >
          <option value="">Geen categorie</option>
          {categories.map((category) => (
            <option key={category.id} value={category.id}>
              {category.name}
            </option>
          ))}
        </select>
        <Button
          type="button"
          size="icon"
          variant="outline"
          aria-label="Categorieën beheren"
          onClick={() => setIsDialogOpen(true)}
          disabled={disabled}
        >
          <Plus className="size-4" />
        </Button>
      </div>
      <CategoryManagerDialog
        open={isDialogOpen}
        onOpenChange={setIsDialogOpen}
        onCategoriesChanged={() => void loadCategories()}
      />
    </>
  )
}
