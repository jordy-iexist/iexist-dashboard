"use client"

import { useRouter } from "next/navigation"
import { useState, useTransition } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { type CustomerWebsiteDetail } from "@/lib/customer-types"

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

type ProfileFormState = {
  name: string
  baseUrl: string
  seoCustomerSince: string
  seoGoals: string
  industry: string
  targetBlogsPerMonth: string
}

function toFormState(customer: CustomerWebsiteDetail): ProfileFormState {
  return {
    name: customer.name,
    baseUrl: customer.base_url,
    seoCustomerSince: customer.seo_customer_since ?? "",
    seoGoals: customer.seo_goals ?? "",
    industry: customer.industry ?? "",
    targetBlogsPerMonth:
      typeof customer.target_blogs_per_month === "number"
        ? String(customer.target_blogs_per_month)
        : "",
  }
}

export function KlantProfielForm({
  customer,
}: {
  customer: CustomerWebsiteDetail
}) {
  const router = useRouter()
  const [form, setForm] = useState<ProfileFormState>(() => toFormState(customer))
  const [isActive, setIsActive] = useState(customer.is_active)
  const [feedback, setFeedback] = useState<Feedback>({ type: null, message: "" })
  const [isPending, startTransition] = useTransition()

  const updateField = (field: keyof ProfileFormState, value: string) => {
    setForm((current) => ({ ...current, [field]: value }))
  }

  const submit = (body: Record<string, unknown>, successMessage: string) => {
    setFeedback({ type: null, message: "" })
    startTransition(async () => {
      try {
        const response = await fetch(
          `/api/customers/${encodeURIComponent(customer.id)}`,
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
        setFeedback({ type: "success", message: successMessage })
        router.refresh()
      } catch (error) {
        setFeedback({
          type: "error",
          message:
            error instanceof Error ? error.message : "Kon klant niet bijwerken.",
        })
      }
    })
  }

  const saveProfile = () => {
    const trimmedTarget = form.targetBlogsPerMonth.trim()
    const parsedTarget = trimmedTarget === "" ? null : Number(trimmedTarget)
    if (parsedTarget !== null && (!Number.isFinite(parsedTarget) || parsedTarget < 0)) {
      setFeedback({
        type: "error",
        message: "Aantal blogs per maand moet een positief getal zijn.",
      })
      return
    }

    submit(
      {
        name: form.name.trim(),
        base_url: form.baseUrl.trim(),
        seo_customer_since: form.seoCustomerSince.trim() || null,
        seo_goals: form.seoGoals.trim() || null,
        industry: form.industry.trim() || null,
        target_blogs_per_month: parsedTarget,
      },
      "Klantprofiel is bijgewerkt."
    )
  }

  const toggleActive = () => {
    const next = !isActive
    setIsActive(next)
    submit(
      { is_active: next },
      next ? "Klant is geactiveerd." : "Klant is gedeactiveerd."
    )
  }

  return (
    <section className="space-y-4 rounded-lg border p-5">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">Klantprofiel</h2>
        <Button
          size="sm"
          variant="outline"
          onClick={toggleActive}
          disabled={isPending}
        >
          {isActive ? "Deactiveren" : "Activeren"}
        </Button>
      </div>

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
            value={form.name}
            onChange={(event) => updateField("name", event.target.value)}
            disabled={isPending}
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs font-medium">Site</label>
          <Input
            value={form.baseUrl}
            onChange={(event) => updateField("baseUrl", event.target.value)}
            disabled={isPending}
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs font-medium">SEO klant sinds</label>
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
          <label className="text-xs font-medium">Branche / categorieën</label>
          <Input
            placeholder="Bijv. Zakelijke dienstverlening"
            value={form.industry}
            onChange={(event) => updateField("industry", event.target.value)}
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

      <div className="flex gap-2">
        <Button onClick={saveProfile} disabled={isPending}>
          Opslaan
        </Button>
        <Button
          variant="outline"
          onClick={() => {
            setForm(toFormState(customer))
            setFeedback({ type: null, message: "" })
          }}
          disabled={isPending}
        >
          Herstellen
        </Button>
      </div>
    </section>
  )
}
