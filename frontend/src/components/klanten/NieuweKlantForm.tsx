"use client"

import { useRouter } from "next/navigation"
import { useState, useTransition } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { CategorySelect } from "@/components/klanten/CategorySelect"

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

type FormState = {
  name: string
  baseUrl: string
  seoCustomerSince: string
  seoGoals: string
  categoryId: string
  targetBlogsPerMonth: string
  targetLinksPerMonth: string
  spreadsheetUrl: string
}

const EMPTY_FORM: FormState = {
  name: "",
  baseUrl: "",
  seoCustomerSince: "",
  seoGoals: "",
  categoryId: "",
  targetBlogsPerMonth: "",
  targetLinksPerMonth: "",
  spreadsheetUrl: "",
}

export function NieuweKlantForm() {
  const router = useRouter()
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [feedback, setFeedback] = useState<Feedback>({ type: null, message: "" })
  const [isPending, startTransition] = useTransition()

  const updateField = (field: keyof FormState, value: string) => {
    setForm((current) => ({ ...current, [field]: value }))
  }

  const canSubmit =
    form.name.trim().length > 0 && form.baseUrl.trim().length > 0 && !isPending

  const create = () => {
    const trimmedTarget = form.targetBlogsPerMonth.trim()
    const parsedTarget = trimmedTarget === "" ? null : Number(trimmedTarget)
    if (parsedTarget !== null && (!Number.isFinite(parsedTarget) || parsedTarget < 0)) {
      setFeedback({
        type: "error",
        message: "Aantal blogs per maand moet een positief getal zijn.",
      })
      return
    }

    const trimmedLinksTarget = form.targetLinksPerMonth.trim()
    const parsedLinksTarget =
      trimmedLinksTarget === "" ? null : Number(trimmedLinksTarget)
    if (
      parsedLinksTarget !== null &&
      (!Number.isFinite(parsedLinksTarget) || parsedLinksTarget < 0)
    ) {
      setFeedback({
        type: "error",
        message: "Aantal links per maand moet een positief getal zijn.",
      })
      return
    }

    setFeedback({ type: null, message: "" })
    startTransition(async () => {
      try {
        const response = await fetch("/api/customers", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: form.name.trim(),
            base_url: form.baseUrl.trim(),
            seo_customer_since: form.seoCustomerSince.trim() || null,
            seo_goals: form.seoGoals.trim() || null,
            category_id: form.categoryId || null,
            target_blogs_per_month: parsedTarget,
            target_links_per_month: parsedLinksTarget,
            spreadsheet_url: form.spreadsheetUrl.trim() || null,
          }),
        })
        const payload = (await response.json().catch(() => null)) as ErrorResponse | null
        if (!response.ok) {
          throw new Error(getErrorMessage(payload, "Kon klant niet toevoegen."))
        }
        router.push("/dashboard/klanten")
        router.refresh()
      } catch (error) {
        setFeedback({
          type: "error",
          message:
            error instanceof Error ? error.message : "Kon klant niet toevoegen.",
        })
      }
    })
  }

  return (
    <section className="space-y-4 rounded-lg border p-5">
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

      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-1">
          <label className="text-xs font-medium">Naam</label>
          <Input
            placeholder="Naam (bijv. Klant A)"
            value={form.name}
            onChange={(event) => updateField("name", event.target.value)}
            disabled={isPending}
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs font-medium">Site</label>
          <Input
            placeholder="https://voorbeeld.nl"
            value={form.baseUrl}
            onChange={(event) => updateField("baseUrl", event.target.value)}
            disabled={isPending}
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs font-medium">Traject gestart</label>
          <Input
            type="date"
            value={form.seoCustomerSince}
            onChange={(event) =>
              updateField("seoCustomerSince", event.target.value)
            }
            disabled={isPending}
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs font-medium">Branche / categorie</label>
          <CategorySelect
            value={form.categoryId}
            onChange={(value) => updateField("categoryId", value)}
            disabled={isPending}
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs font-medium">
            Aantal blogs per maand (doel)
          </label>
          <Input
            type="number"
            min={0}
            placeholder="Bijv. 4"
            value={form.targetBlogsPerMonth}
            onChange={(event) =>
              updateField("targetBlogsPerMonth", event.target.value)
            }
            disabled={isPending}
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs font-medium">
            Aantal links per maand (doel)
          </label>
          <Input
            type="number"
            min={0}
            placeholder="Bijv. 2"
            value={form.targetLinksPerMonth}
            onChange={(event) =>
              updateField("targetLinksPerMonth", event.target.value)
            }
            disabled={isPending}
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs font-medium">
            Externe spreadsheet (optioneel)
          </label>
          <Input
            type="url"
            placeholder="https://docs.google.com/..."
            value={form.spreadsheetUrl}
            onChange={(event) =>
              updateField("spreadsheetUrl", event.target.value)
            }
            disabled={isPending}
          />
          <p className="text-xs text-muted-foreground">
            De interne spreadsheet is altijd bereikbaar via de
            Spreadsheet-knop in de klantenlijst.
          </p>
        </div>
        <div className="space-y-1 md:col-span-2">
          <label className="text-xs font-medium">
            Afspraken met klant / SEO-doelstellingen
          </label>
          <textarea
            className="flex min-h-24 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
            placeholder="Beschrijf de afspraken en SEO-doelstellingen voor deze klant"
            value={form.seoGoals}
            onChange={(event) => updateField("seoGoals", event.target.value)}
            disabled={isPending}
          />
        </div>
      </div>

      <Button onClick={create} disabled={!canSubmit}>
        Klant toevoegen
      </Button>
    </section>
  )
}
