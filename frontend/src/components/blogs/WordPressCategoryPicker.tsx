"use client"

import { useEffect, useMemo, useState } from "react"

import { WordPressCategory } from "@/lib/wordpress-types"

const categoriesCache = new Map<string, Promise<WordPressCategory[]>>()

function fetchCategories(siteId: string): Promise<WordPressCategory[]> {
  const cached = categoriesCache.get(siteId)
  if (cached) {
    return cached
  }

  const request = fetch(
    `/api/wordpress/sites/${encodeURIComponent(siteId)}/categories`,
    { cache: "no-store" }
  ).then(async (response) => {
    const payload = (await response.json().catch(() => null)) as
      | { categories?: WordPressCategory[]; error?: string }
      | null
    if (!response.ok) {
      throw new Error(payload?.error || "Kon categorieën niet ophalen.")
    }
    return Array.isArray(payload?.categories) ? payload.categories : []
  })

  categoriesCache.set(siteId, request)
  request.catch(() => categoriesCache.delete(siteId))
  return request
}

function orderByHierarchy(categories: WordPressCategory[]) {
  const childrenByParent = new Map<number, WordPressCategory[]>()
  const ids = new Set(categories.map((category) => category.id))
  for (const category of categories) {
    const parent = ids.has(category.parent) ? category.parent : 0
    const siblings = childrenByParent.get(parent) ?? []
    siblings.push(category)
    childrenByParent.set(parent, siblings)
  }

  const ordered: { category: WordPressCategory; depth: number }[] = []
  const visit = (parent: number, depth: number) => {
    for (const category of childrenByParent.get(parent) ?? []) {
      ordered.push({ category, depth })
      visit(category.id, depth + 1)
    }
  }
  visit(0, 0)
  return ordered
}

/** Converts a `datetime-local` value (local time) to an ISO string in UTC. */
export function localDateTimeToIso(value: string): string | null {
  if (!value) {
    return null
  }
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date.toISOString()
}

export function isFutureLocalDateTime(value: string) {
  const date = new Date(value)
  return !Number.isNaN(date.getTime()) && date.getTime() > Date.now()
}

type WordPressCategoryPickerProps = {
  siteId: string
  siteName?: string
  selectedIds: number[]
  onChange: (ids: number[]) => void
  disabled?: boolean
}

export function WordPressCategoryPicker({
  siteId,
  siteName,
  selectedIds,
  onChange,
  disabled,
}: WordPressCategoryPickerProps) {
  const [result, setResult] = useState<{
    siteId: string
    categories: WordPressCategory[] | null
    error: string | null
  } | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchCategories(siteId)
      .then((categories) => {
        if (!cancelled) setResult({ siteId, categories, error: null })
      })
      .catch((err) => {
        if (!cancelled) {
          setResult({
            siteId,
            categories: null,
            error: err instanceof Error ? err.message : "Kon categorieën niet ophalen.",
          })
        }
      })
    return () => {
      cancelled = true
    }
  }, [siteId])

  const current = result?.siteId === siteId ? result : null
  const categories = current?.categories ?? null
  const error = current?.error ?? null

  const ordered = useMemo(
    () => (categories ? orderByHierarchy(categories) : []),
    [categories]
  )

  const toggle = (id: number, checked: boolean) => {
    if (checked) {
      onChange(selectedIds.includes(id) ? selectedIds : [...selectedIds, id])
    } else {
      onChange(selectedIds.filter((value) => value !== id))
    }
  }

  return (
    <div className="space-y-1.5">
      <p className="text-xs font-medium text-muted-foreground">
        Categorieën{siteName ? ` – ${siteName}` : ""}
        {selectedIds.length > 0 ? ` (${selectedIds.length})` : ""}
      </p>
      {error ? (
        <p className="text-xs text-red-600">{error}</p>
      ) : categories === null ? (
        <p className="text-xs text-muted-foreground">Categorieën laden...</p>
      ) : ordered.length === 0 ? (
        <p className="text-xs text-muted-foreground">Geen categorieën gevonden.</p>
      ) : (
        <div className="max-h-40 space-y-1 overflow-y-auto rounded-md border px-2 py-1.5">
          {ordered.map(({ category, depth }) => (
            <label
              key={category.id}
              className="flex items-center gap-2 text-sm"
              style={{ paddingLeft: depth * 16 }}
            >
              <input
                type="checkbox"
                checked={selectedIds.includes(category.id)}
                onChange={(event) => toggle(category.id, event.target.checked)}
                disabled={disabled}
              />
              <span>{category.name || `#${category.id}`}</span>
            </label>
          ))}
        </div>
      )}
    </div>
  )
}
