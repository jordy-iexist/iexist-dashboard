"use client"

import { Pencil, Trash2 } from "lucide-react"
import { useCallback, useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { type CustomerCategory } from "@/lib/customer-types"

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

export function CategoryManagerDialog({
  open,
  onOpenChange,
  onCategoriesChanged,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCategoriesChanged?: () => void
}) {
  const [categories, setCategories] = useState<CustomerCategory[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [feedback, setFeedback] = useState<Feedback>({ type: null, message: "" })
  const [newName, setNewName] = useState("")
  const [isCreating, setIsCreating] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editingName, setEditingName] = useState("")
  const [isSavingEdit, setIsSavingEdit] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)

  const loadCategories = useCallback(async () => {
    setIsLoading(true)
    try {
      const response = await fetch("/api/customer-categories", { cache: "no-store" })
      const payload = (await response.json().catch(() => null)) as
        | { categories?: CustomerCategory[] }
        | ErrorResponse
        | null
      if (!response.ok) {
        throw new Error(
          getErrorMessage(payload as ErrorResponse | null, "Kon categorieën niet ophalen.")
        )
      }
      setCategories((payload as { categories?: CustomerCategory[] })?.categories ?? [])
    } catch (error) {
      setFeedback({
        type: "error",
        message:
          error instanceof Error ? error.message : "Kon categorieën niet ophalen.",
      })
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    if (open) {
      setFeedback({ type: null, message: "" })
      void loadCategories()
    }
  }, [open, loadCategories])

  const createCategory = async () => {
    const name = newName.trim()
    if (!name) return

    setIsCreating(true)
    setFeedback({ type: null, message: "" })
    try {
      const response = await fetch("/api/customer-categories", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      })
      const payload = (await response.json().catch(() => null)) as ErrorResponse | null
      if (!response.ok) {
        throw new Error(getErrorMessage(payload, "Kon categorie niet toevoegen."))
      }
      setNewName("")
      await loadCategories()
      onCategoriesChanged?.()
    } catch (error) {
      setFeedback({
        type: "error",
        message:
          error instanceof Error ? error.message : "Kon categorie niet toevoegen.",
      })
    } finally {
      setIsCreating(false)
    }
  }

  const startEdit = (category: CustomerCategory) => {
    setEditingId(category.id)
    setEditingName(category.name)
  }

  const cancelEdit = () => {
    setEditingId(null)
    setEditingName("")
  }

  const saveEdit = async () => {
    if (!editingId) return
    const name = editingName.trim()
    if (!name) return

    setIsSavingEdit(true)
    setFeedback({ type: null, message: "" })
    try {
      const response = await fetch(`/api/customer-categories/${editingId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      })
      const payload = (await response.json().catch(() => null)) as ErrorResponse | null
      if (!response.ok) {
        throw new Error(getErrorMessage(payload, "Kon categorie niet bijwerken."))
      }
      cancelEdit()
      await loadCategories()
      onCategoriesChanged?.()
    } catch (error) {
      setFeedback({
        type: "error",
        message:
          error instanceof Error ? error.message : "Kon categorie niet bijwerken.",
      })
    } finally {
      setIsSavingEdit(false)
    }
  }

  const deleteCategory = async (category: CustomerCategory) => {
    const confirmed = window.confirm(
      category.customer_count > 0
        ? `${category.customer_count} klant${category.customer_count === 1 ? "" : "en"} verliez${category.customer_count === 1 ? "t" : "en"} deze categorie. Weet je het zeker?`
        : `Categorie "${category.name}" verwijderen?`
    )
    if (!confirmed) return

    setDeletingId(category.id)
    setFeedback({ type: null, message: "" })
    try {
      const response = await fetch(`/api/customer-categories/${category.id}`, {
        method: "DELETE",
      })
      const payload = (await response.json().catch(() => null)) as ErrorResponse | null
      if (!response.ok) {
        throw new Error(getErrorMessage(payload, "Kon categorie niet verwijderen."))
      }
      await loadCategories()
      onCategoriesChanged?.()
    } catch (error) {
      setFeedback({
        type: "error",
        message:
          error instanceof Error ? error.message : "Kon categorie niet verwijderen.",
      })
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Categorieën beheren</DialogTitle>
        </DialogHeader>

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

        <div className="flex items-center gap-2">
          <Input
            placeholder="Nieuwe categorie"
            value={newName}
            onChange={(event) => setNewName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault()
                void createCategory()
              }
            }}
            disabled={isCreating}
          />
          <Button
            onClick={() => void createCategory()}
            disabled={isCreating || !newName.trim()}
          >
            Toevoegen
          </Button>
        </div>

        <div className="max-h-72 space-y-1 overflow-y-auto">
          {isLoading ? (
            <p className="text-sm text-muted-foreground">Categorieën laden...</p>
          ) : categories.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Nog geen categorieën aangemaakt.
            </p>
          ) : (
            categories.map((category) => (
              <div
                key={category.id}
                className="flex items-center justify-between gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-muted"
              >
                {editingId === category.id ? (
                  <div className="flex flex-1 items-center gap-2">
                    <Input
                      value={editingName}
                      onChange={(event) => setEditingName(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          event.preventDefault()
                          void saveEdit()
                        }
                        if (event.key === "Escape") {
                          cancelEdit()
                        }
                      }}
                      autoFocus
                      disabled={isSavingEdit}
                    />
                    <Button
                      size="sm"
                      onClick={() => void saveEdit()}
                      disabled={isSavingEdit || !editingName.trim()}
                    >
                      Opslaan
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={cancelEdit}
                      disabled={isSavingEdit}
                    >
                      Annuleren
                    </Button>
                  </div>
                ) : (
                  <>
                    <div className="min-w-0">
                      <p className="truncate font-medium">{category.name}</p>
                      <p className="text-xs text-muted-foreground">
                        {category.customer_count} klant
                        {category.customer_count === 1 ? "" : "en"}
                      </p>
                    </div>
                    <div className="flex shrink-0 items-center gap-1">
                      <Button
                        size="icon-sm"
                        variant="ghost"
                        aria-label={`${category.name} hernoemen`}
                        onClick={() => startEdit(category)}
                      >
                        <Pencil className="size-4" />
                      </Button>
                      <Button
                        size="icon-sm"
                        variant="ghost"
                        aria-label={`${category.name} verwijderen`}
                        onClick={() => void deleteCategory(category)}
                        disabled={deletingId === category.id}
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    </div>
                  </>
                )}
              </div>
            ))
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
