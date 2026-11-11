"use client"

import { Check, Copy } from "lucide-react"
import { useState } from "react"

import { Pill } from "@/components/livegang/shared"
import type {
  ImageProblem,
  InternalLinkDetails,
  LinkAnchor,
  LinkProblem,
  RedirectDetails,
} from "@/lib/launch-checklist"

/** Checklistpunten waarvoor we de onderliggende links/afbeeldingen kunnen tonen. */
export const DETAIL_ITEM_KEYS = new Set(["c3_redirects_404", "c3_images", "c3_internal_links"])

const linkClass = "break-all hover:text-primary hover:underline"

/** Welke links, afbeeldingen of linkteksten achter een fase-3 melding zitten (niets als er geen lijst is). */
export function CheckDetails({ itemKey, details, className }: { itemKey: string; details: unknown; className?: string }) {
  if (!details || typeof details !== "object") return null
  let content: React.ReactNode = null
  if (itemKey === "c3_redirects_404") {
    const d = details as RedirectDetails
    if (d.broken?.length || d.redirects?.length) content = <RedirectList details={d} />
  } else if (itemKey === "c3_images") {
    const images = (details as { images?: ImageProblem[] }).images ?? []
    if (images.length) content = <ImageList images={images} />
  } else if (itemKey === "c3_internal_links") {
    const links = (details as InternalLinkDetails).generic ?? []
    if (links.length) content = <GenericLinkList links={links} />
  }
  return content ? <div className={className}>{content}</div> : null
}

function RedirectList({ details }: { details: RedirectDetails }) {
  const broken = details.broken ?? []
  const redirects = details.redirects ?? []
  return (
    <div className="space-y-3">
      <LinkGroup title="Kapot (404/fout)" rows={broken} total={details.broken_total} />
      <LinkGroup title="Redirect" rows={redirects} total={details.redirects_total} />
    </div>
  )
}

function LinkGroup({ title, rows, total }: { title: string; rows: LinkProblem[]; total?: number }) {
  if (!rows.length) return null
  const more = (total ?? rows.length) - rows.length
  return (
    <div>
      <p className="mb-1 text-xs font-medium text-muted-foreground">
        {title} ({total ?? rows.length})
      </p>
      <ul className="divide-y rounded-md border text-xs">
        {rows.map((row) => (
          <LinkRow key={row.url} row={row} />
        ))}
      </ul>
      {more > 0 && <p className="mt-1 text-xs text-muted-foreground">en nog {more}…</p>}
    </div>
  )
}

function LinkRow({ row }: { row: LinkProblem }) {
  // Oudere scans bewaarden alleen de eerste ankertekst en de absolute URL.
  // Daar is de plek (tekst of menu/footer) onbekend, dus geen label.
  const legacy = !row.anchors?.length
  const anchors: LinkAnchor[] = legacy ? [{ text: row.text, href: row.url, in_content: true }] : row.anchors!
  const finalStatus = row.final_status ?? null
  const showFinal = row.final_url && row.final_url !== row.url
  return (
    <li className="space-y-1.5 px-3 py-2">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <StatusPill status={row.status} />
        <a href={row.url} target="_blank" rel="noreferrer noopener" className={linkClass}>
          {row.url}
        </a>
        {showFinal && (
          <>
            <span className="text-muted-foreground">→</span>
            <a href={row.final_url!} target="_blank" rel="noreferrer noopener" className={linkClass}>
              {row.final_url}
            </a>
            {finalStatus !== null && finalStatus !== 200 && <StatusPill status={finalStatus} />}
          </>
        )}
      </div>
      <ul className="space-y-1">
        {anchors.map((anchor, index) => (
          <li key={`${index}-${anchor.href}-${anchor.text}`} className="flex flex-wrap items-center gap-2">
            {!legacy && (
              <Pill tone={anchor.in_content ? "blue" : "muted"}>{anchor.in_content ? "In tekst" : "Menu/footer"}</Pill>
            )}
            <span className="font-medium">{anchor.text || <em className="text-muted-foreground">— geen tekst —</em>}</span>
            <AnchorTag anchor={anchor} />
          </li>
        ))}
      </ul>
    </li>
  )
}

function StatusPill({ status }: { status: number | null }) {
  if (status === null || status === undefined) return <Pill tone="red">fout</Pill>
  return <Pill tone={status >= 400 ? "red" : status >= 300 ? "amber" : "muted"}>{status}</Pill>
}

/** De <a>-tag zoals hij in de HTML staat, met kopieerknop om hem in de editor te zoeken. */
function AnchorTag({ anchor }: { anchor: LinkAnchor }) {
  const [copied, setCopied] = useState(false)
  const tag = `<a href="${anchor.href}">${anchor.text}</a>`

  async function copy() {
    try {
      await navigator.clipboard.writeText(anchor.href)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // Klembord niet beschikbaar: de tag staat zichtbaar en is te selecteren.
    }
  }

  return (
    <span className="flex min-w-0 items-center gap-1">
      <code className="min-w-0 break-all rounded bg-muted px-1.5 py-0.5 font-mono text-[11px]">{tag}</code>
      <button
        type="button"
        onClick={() => void copy()}
        title="Href kopiëren"
        aria-label="Href kopiëren"
        className="shrink-0 rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
      >
        {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
      </button>
    </span>
  )
}

function ImageList({ images }: { images: ImageProblem[] }) {
  return (
    <ul className="divide-y rounded-md border text-xs">
      {images.map((image, index) => (
        <li key={`${index}-${image.src}`} className="flex flex-wrap items-center gap-2 px-3 py-2">
          {image.missing_alt && <Pill tone="red">geen alt</Pill>}
          {image.generic_filename && <Pill tone="amber">nietszeggende bestandsnaam</Pill>}
          <span className="font-medium">{image.filename || "—"}</span>
          <a href={image.src} target="_blank" rel="noreferrer noopener" className={`${linkClass} text-muted-foreground`}>
            {image.src}
          </a>
          {!image.missing_alt && image.alt !== null && (
            <span className="text-muted-foreground">alt: “{image.alt || "leeg"}”</span>
          )}
        </li>
      ))}
    </ul>
  )
}

function GenericLinkList({ links }: { links: { url: string; text: string }[] }) {
  return (
    <ul className="divide-y rounded-md border text-xs">
      {links.map((link, index) => (
        <li key={`${index}-${link.url}`} className="flex flex-wrap items-center gap-2 px-3 py-2">
          <span className="font-medium">“{link.text}”</span>
          <span className="text-muted-foreground">→</span>
          <a href={link.url} target="_blank" rel="noreferrer noopener" className={linkClass}>
            {link.url}
          </a>
        </li>
      ))}
    </ul>
  )
}
