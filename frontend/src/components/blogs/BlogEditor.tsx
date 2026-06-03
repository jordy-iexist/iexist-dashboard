"use client"

import { useMemo, useState, useTransition } from "react"
import { useRouter } from "next/navigation"
import ReactMarkdown from "react-markdown"
import { Copy, Check } from "lucide-react"

import { Button } from "@/components/ui/button"

type BlogEditorProps = {
  blogId: string
  initialContent: string
}

type SaveResponse =
  | {
      blog: {
        id: string
        content: string
        created_at: string
      }
    }
  | {
      error: string
    }

export function BlogEditor({ blogId, initialContent }: BlogEditorProps) {
  const router = useRouter()
  const [isEditing, setIsEditing] = useState(false)
  const [content, setContent] = useState(initialContent)
  const [draft, setDraft] = useState(initialContent)
  const [feedback, setFeedback] = useState<{
    type: "success" | "error" | null
    message: string
  }>({ type: null, message: "" })
  const [isPending, startTransition] = useTransition()
  const [justCopied, setJustCopied] = useState(false)

  const hasChanges = useMemo(
    () => draft.trim() !== content.trim(),
    [content, draft]
  )

  const copyContent = async () => {
    try {
      await navigator.clipboard.writeText(content)
      setJustCopied(true)
      setFeedback({ type: null, message: "" })
      setTimeout(() => setJustCopied(false), 1500)
    } catch {
      setFeedback({ type: "error", message: "Kopiëren naar klembord is mislukt." })
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
        const response = await fetch(`/api/blogs/${blogId}`, {
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
              : "Opslaan van blog is mislukt."
          throw new Error(errorMessage)
        }

        if (!payload || !("blog" in payload) || !payload.blog?.content) {
          throw new Error("Onverwachte response van server.")
        }

        setContent(payload.blog.content)
        setDraft(payload.blog.content)
        setIsEditing(false)
        setFeedback({
          type: "success",
          message: "Blog opgeslagen in de backend.",
        })
        router.refresh()
      } catch (error) {
        const message =
          error instanceof Error
            ? error.message
            : "Opslaan van blog is mislukt."
        setFeedback({
          type: "error",
          message,
        })
      }
    })
  }

  return (
    <section className="space-y-4 rounded-lg border bg-card p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold">Blog inhoud</h2>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="icon-sm"
            onClick={copyContent}
            aria-label={justCopied ? "Gekopieerd" : "Kopieer blog naar klembord"}
            title={justCopied ? "Gekopieerd" : "Kopieer blog naar klembord"}
          >
            {justCopied ? <Check /> : <Copy />}
          </Button>

          {!isEditing ? (
            <Button onClick={startEditing}>Bewerk blog</Button>
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
          )}
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
        <article className="prose prose-sm max-w-none leading-7">
          <ReactMarkdown>{content}</ReactMarkdown>
        </article>
      ) : (
        <div className="space-y-2">
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            className="min-h-[420px] w-full rounded-md border bg-background px-3 py-2 text-sm leading-7"
            disabled={isPending}
          />
          <p className="text-xs text-muted-foreground">
            Wijzigingen worden direct naar de backend geschreven bij opslaan.
          </p>
        </div>
      )}
    </section>
  )
}
