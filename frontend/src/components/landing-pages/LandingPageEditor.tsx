"use client"

import { useEffect, useMemo, useRef, useState, useTransition } from "react"
import { useRouter } from "next/navigation"
import ReactMarkdown from "react-markdown"
import { Copy, Check } from "lucide-react"

import { Button } from "@/components/ui/button"
import { BlogMarkdownEditor } from "@/components/blogs/BlogMarkdownEditor"
import { type CustomersResponse } from "@/lib/customer-types"
import { LandingPageMetaPanel } from "./LandingPageMetaPanel"

type Props = {
  landingPageId: string
  initialContent: string
  initialMetaTitle: string | null
  initialMetaDescription: string | null
  initialSlug: string | null
  isOwner?: boolean
  initialIsPublic?: boolean
  initialCustomerWebsiteId?: string | null
}

type SaveResponse =
  | {
      landing_page: {
        id: string
        content: string
        created_at: string
      }
    }
  | {
      error: string
    }

export function LandingPageEditor({
  landingPageId,
  initialContent,
  initialMetaTitle,
  initialMetaDescription,
  initialSlug,
  isOwner = true,
  initialIsPublic = false,
  initialCustomerWebsiteId = null,
}: Props) {
  const router = useRouter()
  const [isEditing, setIsEditing] = useState(false)
  const [content, setContent] = useState(initialContent)
  const [draft, setDraft] = useState(initialContent)
  const [isPublic, setIsPublic] = useState(initialIsPublic)
  const [isTogglingShare, setIsTogglingShare] = useState(false)
  const [customerWebsiteId, setCustomerWebsiteId] = useState(
    initialCustomerWebsiteId ?? ""
  )
  const [customers, setCustomers] = useState<{ id: string; name: string }[]>([])
  const [isSavingCustomer, setIsSavingCustomer] = useState(false)

  useEffect(() => {
    if (!isOwner) return
    let cancelled = false
    fetch("/api/customers", { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : null))
      .then((payload: CustomersResponse | null) => {
        if (!cancelled && payload?.websites) {
          setCustomers(payload.websites.map(({ id, name }) => ({ id, name })))
        }
      })
      .catch(() => {
        // Klant-select is optioneel; zonder lijst blijft de dropdown leeg.
      })
    return () => {
      cancelled = true
    }
  }, [isOwner])
  const [feedback, setFeedback] = useState<{
    type: "success" | "error" | null
    message: string
  }>({ type: null, message: "" })
  const [isPending, startTransition] = useTransition()
  const [justCopied, setJustCopied] = useState(false)
  const articleRef = useRef<HTMLElement>(null)

  const hasChanges = useMemo(
    () => draft.trim() !== content.trim(),
    [content, draft]
  )

  const copyContent = async () => {
    try {
      const html = articleRef.current?.innerHTML
      if (html) {
        await navigator.clipboard.write([
          new ClipboardItem({
            "text/html": new Blob([html], { type: "text/html" }),
            "text/plain": new Blob([content], { type: "text/plain" }),
          }),
        ])
      } else {
        await navigator.clipboard.writeText(content)
      }
      setJustCopied(true)
      setFeedback({ type: null, message: "" })
      setTimeout(() => setJustCopied(false), 1500)
    } catch {
      setFeedback({ type: "error", message: "Kopiëren naar klembord is mislukt." })
    }
  }

  const toggleShareWithTeam = async () => {
    const next = !isPublic
    setIsTogglingShare(true)
    setFeedback({ type: null, message: "" })
    try {
      const response = await fetch(`/api/landing-pages/${landingPageId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_public: next }),
      })
      if (!response.ok) {
        const payload = (await response.json().catch(() => null)) as
          | { error?: string }
          | null
        throw new Error(payload?.error || "Delen aanpassen is mislukt.")
      }
      setIsPublic(next)
      setFeedback({
        type: "success",
        message: next
          ? "Landingspagina is nu gedeeld met het team."
          : "Landingspagina is niet meer gedeeld met het team.",
      })
      router.refresh()
    } catch (error) {
      setFeedback({
        type: "error",
        message:
          error instanceof Error ? error.message : "Delen aanpassen is mislukt.",
      })
    } finally {
      setIsTogglingShare(false)
    }
  }

  const changeCustomer = async (nextCustomerId: string) => {
    const previous = customerWebsiteId
    setCustomerWebsiteId(nextCustomerId)
    setIsSavingCustomer(true)
    setFeedback({ type: null, message: "" })
    try {
      const response = await fetch(`/api/landing-pages/${landingPageId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ customer_website_id: nextCustomerId || null }),
      })
      if (!response.ok) {
        const payload = (await response.json().catch(() => null)) as
          | { error?: string }
          | null
        throw new Error(payload?.error || "Klant aanpassen is mislukt.")
      }
      setFeedback({
        type: "success",
        message: nextCustomerId
          ? "Landingspagina is gekoppeld aan de klant."
          : "Klantkoppeling is verwijderd.",
      })
      router.refresh()
    } catch (error) {
      setCustomerWebsiteId(previous)
      setFeedback({
        type: "error",
        message:
          error instanceof Error ? error.message : "Klant aanpassen is mislukt.",
      })
    } finally {
      setIsSavingCustomer(false)
    }
  }

  const startEditing = () => {
    setDraft(content)
    setFeedback({ type: null, message: "" })
    setIsEditing(true)
  }

  const cancelEditing = () => {
    setDraft(content)
    setFeedback({ type: null, message: "" })
    setIsEditing(false)
  }

  const saveChanges = () => {
    setFeedback({ type: null, message: "" })
    startTransition(async () => {
      try {
        const response = await fetch(`/api/landing-pages/${landingPageId}`, {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ content: draft }),
        })
        const payload = (await response.json().catch(() => null)) as
          | SaveResponse
          | null

        if (!response.ok) {
          const errorMessage =
            payload && "error" in payload
              ? payload.error
              : "Opslaan van landingspagina is mislukt."
          throw new Error(errorMessage)
        }

        if (!payload || !("landing_page" in payload) || !payload.landing_page?.content) {
          throw new Error("Onverwachte response van server.")
        }

        setContent(payload.landing_page.content)
        setDraft(payload.landing_page.content)
        setIsEditing(false)
        setFeedback({
          type: "success",
          message: "Landingspagina opgeslagen.",
        })
        router.refresh()
      } catch (error) {
        const message =
          error instanceof Error
            ? error.message
            : "Opslaan van landingspagina is mislukt."
        setFeedback({
          type: "error",
          message,
        })
      }
    })
  }

  return (
    <div className="space-y-6">
      {isOwner && (
        <LandingPageMetaPanel
          landingPageId={landingPageId}
          initialMetaTitle={initialMetaTitle}
          initialMetaDescription={initialMetaDescription}
          initialSlug={initialSlug}
        />
      )}

      <section className="space-y-4 rounded-lg border bg-card p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-semibold">Pagina inhoud</h2>

          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="icon-sm"
              onClick={copyContent}
              aria-label={justCopied ? "Gekopieerd" : "Kopieer inhoud naar klembord"}
              title={justCopied ? "Gekopieerd" : "Kopieer inhoud naar klembord"}
            >
              {justCopied ? <Check /> : <Copy />}
            </Button>

            {isOwner && (
              <select
                value={customerWebsiteId}
                onChange={(event) => changeCustomer(event.target.value)}
                disabled={isSavingCustomer}
                aria-label="Klant"
                className="h-8 rounded-md border border-input bg-background px-2 text-sm focus-visible:outline-none"
              >
                <option value="">Geen klant</option>
                {customers.map((customer) => (
                  <option key={customer.id} value={customer.id}>
                    {customer.name}
                  </option>
                ))}
              </select>
            )}

            {isOwner && (
              <label className="inline-flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm">
                <input
                  type="checkbox"
                  checked={isPublic}
                  onChange={toggleShareWithTeam}
                  disabled={isTogglingShare}
                />
                Gedeeld met team
              </label>
            )}

            {isOwner &&
              (!isEditing ? (
                <Button onClick={startEditing}>Bewerk inhoud</Button>
              ) : (
                <>
                  <Button
                    variant="outline"
                    onClick={cancelEditing}
                    disabled={isPending}
                  >
                    Annuleren
                  </Button>
                  <Button
                    onClick={saveChanges}
                    disabled={isPending || !hasChanges || draft.trim().length === 0}
                  >
                    {isPending ? "Opslaan..." : "Opslaan"}
                  </Button>
                </>
              ))}
          </div>
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

        {!isEditing ? (
          <article ref={articleRef} className="prose prose-sm max-w-none leading-7">
            <ReactMarkdown>{content}</ReactMarkdown>
          </article>
        ) : (
          <div className="space-y-2">
            <BlogMarkdownEditor
              value={draft}
              onChange={setDraft}
              disabled={isPending}
            />
            <p className="text-xs text-muted-foreground">
              Wijzigingen worden direct naar de backend geschreven bij opslaan.
            </p>
          </div>
        )}
      </section>
    </div>
  )
}
