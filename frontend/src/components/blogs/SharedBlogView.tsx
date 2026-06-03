"use client"

import { useRef, useState } from "react"
import ReactMarkdown from "react-markdown"
import { Copy, Check, Download } from "lucide-react"

import { Button } from "@/components/ui/button"
import { type BlogImageItem } from "@/lib/blog-types"

type SharedBlogViewProps = {
  content: string
  images: BlogImageItem[]
  createdAt: string
}

function formatDate(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ""
  return new Intl.DateTimeFormat("nl-NL", {
    dateStyle: "long",
  }).format(date)
}

export function SharedBlogView({ content, images, createdAt }: SharedBlogViewProps) {
  const articleRef = useRef<HTMLElement>(null)
  const [justCopied, setJustCopied] = useState(false)

  const copyAsHtml = async () => {
    const html = articleRef.current?.innerHTML ?? ""
    try {
      await navigator.clipboard.write([
        new ClipboardItem({
          "text/html": new Blob([html], { type: "text/html" }),
          "text/plain": new Blob([content], { type: "text/plain" }),
        }),
      ])
    } catch {
      await navigator.clipboard.writeText(content).catch(() => undefined)
    }
    setJustCopied(true)
    setTimeout(() => setJustCopied(false), 1500)
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        {createdAt && (
          <p className="text-sm text-muted-foreground">{formatDate(createdAt)}</p>
        )}
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={copyAsHtml}
          className="flex items-center gap-2"
        >
          {justCopied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
          {justCopied ? "Gekopieerd!" : "Kopieer als HTML"}
        </Button>
      </div>

      <article ref={articleRef} className="prose prose-sm max-w-none leading-7">
        <ReactMarkdown>{content}</ReactMarkdown>
      </article>

      {images.length > 0 && (
        <section className="space-y-3 rounded-lg border bg-card p-5">
          <h2 className="text-sm font-semibold">Bijlagen</h2>
          <ul className="space-y-2">
            {images.map((image, index) => (
              <li key={image.id}>
                {image.signed_url ? (
                  <a
                    href={image.signed_url}
                    download
                    className="inline-flex items-center gap-2 text-sm underline underline-offset-2 hover:text-foreground"
                  >
                    <Download className="h-4 w-4 shrink-0" />
                    {image.is_primary ? "Primaire afbeelding" : `Afbeelding ${index + 1}`}
                    <span className="text-muted-foreground">
                      ({(image.file_size_bytes / 1024).toFixed(0)} KB)
                    </span>
                  </a>
                ) : (
                  <span className="text-sm text-muted-foreground">
                    {image.is_primary ? "Primaire afbeelding" : `Afbeelding ${index + 1}`}{" "}
                    (niet beschikbaar)
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
