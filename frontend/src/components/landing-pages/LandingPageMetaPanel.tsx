"use client"

import { useState } from "react"
import { Copy, Check } from "lucide-react"
import { Button } from "@/components/ui/button"

type Props = {
  landingPageId: string
  initialMetaTitle: string | null
  initialMetaDescription: string | null
  initialSlug: string | null
}

function useClipboardCopy(getValue: () => string, onError?: () => void) {
  const [justCopied, setJustCopied] = useState(false)

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(getValue())
      setJustCopied(true)
      setTimeout(() => setJustCopied(false), 1500)
    } catch {
      onError?.()
    }
  }

  return { justCopied, copy }
}

function metaTitleColor(len: number): string {
  if (len === 0) return "text-muted-foreground"
  if (len <= 60) return "text-green-600"
  return "text-red-600"
}

function metaDescriptionColor(len: number): string {
  if (len === 0) return "text-muted-foreground"
  if (len >= 120 && len <= 155) return "text-green-600"
  if (len > 155) return "text-red-600"
  return "text-yellow-600"
}

export function LandingPageMetaPanel({
  landingPageId,
  initialMetaTitle,
  initialMetaDescription,
  initialSlug,
}: Props) {
  const [metaTitle, setMetaTitle] = useState(initialMetaTitle ?? "")
  const [metaDescription, setMetaDescription] = useState(initialMetaDescription ?? "")
  const [slug, setSlug] = useState(initialSlug ?? "")
  const [feedback, setFeedback] = useState<{
    type: "success" | "error" | null
    message: string
  }>({ type: null, message: "" })
  const [saving, setSaving] = useState(false)

  const clipboardError = () =>
    setFeedback({ type: "error", message: "Kopiëren naar klembord mislukt." })

  const titleCopy = useClipboardCopy(() => metaTitle, clipboardError)
  const descCopy = useClipboardCopy(() => metaDescription, clipboardError)
  const slugCopy = useClipboardCopy(() => slug, clipboardError)

  const save = async () => {
    setSaving(true)
    setFeedback({ type: null, message: "" })
    try {
      const response = await fetch(`/api/landing-pages/${landingPageId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          meta_title: metaTitle || null,
          meta_description: metaDescription || null,
          slug: slug || null,
        }),
      })

      if (!response.ok) {
        const data = (await response.json().catch(() => null)) as
          | { error?: string }
          | null
        setFeedback({
          type: "error",
          message: data?.error ?? "Opslaan van meta-gegevens is mislukt.",
        })
        return
      }

      setFeedback({ type: "success", message: "Meta-gegevens opgeslagen." })
    } catch {
      setFeedback({ type: "error", message: "Er is een fout opgetreden." })
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="space-y-4 rounded-lg border bg-card p-5">
      <h2 className="text-lg font-semibold">SEO meta-gegevens</h2>

      {/* Meta title */}
      <div className="space-y-1.5">
        <label className="text-sm font-medium" htmlFor="lp-meta-title">
          Meta titel
        </label>
        <div className="flex items-center gap-2">
          <input
            id="lp-meta-title"
            type="text"
            value={metaTitle}
            onChange={(e) => setMetaTitle(e.target.value)}
            placeholder="Meta titel..."
            className="flex-1 rounded-md border bg-background px-3 py-1.5 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
          <Button
            type="button"
            variant="outline"
            size="icon-sm"
            onClick={titleCopy.copy}
            aria-label={titleCopy.justCopied ? "Gekopieerd" : "Kopieer meta titel"}
            title={titleCopy.justCopied ? "Gekopieerd" : "Kopieer meta titel"}
          >
            {titleCopy.justCopied ? <Check /> : <Copy />}
          </Button>
        </div>
        <p className={`text-xs ${metaTitleColor(metaTitle.length)}`}>
          {metaTitle.length} / 60 tekens
          {metaTitle.length > 60 && " — te lang"}
        </p>
      </div>

      {/* Meta description */}
      <div className="space-y-1.5">
        <label className="text-sm font-medium" htmlFor="lp-meta-description">
          Meta omschrijving
        </label>
        <div className="flex items-center gap-2">
          <input
            id="lp-meta-description"
            type="text"
            value={metaDescription}
            onChange={(e) => setMetaDescription(e.target.value)}
            placeholder="Meta omschrijving..."
            className="flex-1 rounded-md border bg-background px-3 py-1.5 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
          <Button
            type="button"
            variant="outline"
            size="icon-sm"
            onClick={descCopy.copy}
            aria-label={descCopy.justCopied ? "Gekopieerd" : "Kopieer meta omschrijving"}
            title={descCopy.justCopied ? "Gekopieerd" : "Kopieer meta omschrijving"}
          >
            {descCopy.justCopied ? <Check /> : <Copy />}
          </Button>
        </div>
        <p className={`text-xs ${metaDescriptionColor(metaDescription.length)}`}>
          {metaDescription.length} tekens (ideaal: 120–155)
          {metaDescription.length > 155 && " — te lang"}
          {metaDescription.length > 0 && metaDescription.length < 120 && " — te kort"}
        </p>
      </div>

      {/* Slug */}
      <div className="space-y-1.5">
        <label className="text-sm font-medium" htmlFor="lp-slug">
          Slug
        </label>
        <div className="flex items-center gap-2">
          <input
            id="lp-slug"
            type="text"
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            placeholder="pagina-slug..."
            className="flex-1 rounded-md border bg-background px-3 py-1.5 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
          <Button
            type="button"
            variant="outline"
            size="icon-sm"
            onClick={slugCopy.copy}
            aria-label={slugCopy.justCopied ? "Gekopieerd" : "Kopieer slug"}
            title={slugCopy.justCopied ? "Gekopieerd" : "Kopieer slug"}
          >
            {slugCopy.justCopied ? <Check /> : <Copy />}
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">{slug.length} tekens</p>
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

      <Button onClick={save} disabled={saving}>
        {saving ? "Opslaan..." : "Opslaan"}
      </Button>
    </section>
  )
}
