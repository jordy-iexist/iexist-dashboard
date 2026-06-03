import Link from "next/link"
import { notFound, redirect } from "next/navigation"
import { unstable_noStore as noStore } from "next/cache"

import { BlogDeleteButton } from "@/components/blogs/BlogDeleteButton"
import { BlogEditor } from "@/components/blogs/BlogEditor"
import { BlogImagePanel } from "@/components/blogs/BlogImagePanel"
import { BlogPublishPanel } from "@/components/blogs/BlogPublishPanel"
import {
  getBackendApiUrl,
  getBackendAuthorizationValue,
} from "@/lib/backend-api"
import { type BlogDetailResponse } from "@/lib/blog-types"

export const metadata = {
  title: "Blog Detail",
}

type BlogDetailPageProps = {
  params: Promise<{ blogId: string }>
}

function formatCreatedAt(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return "-"
  }

  return new Intl.DateTimeFormat("nl-NL", {
    dateStyle: "full",
    timeStyle: "short",
  }).format(date)
}

function AnchorDisplay({
  label,
  text,
  url,
}: {
  label: string
  text?: string
  url?: string
}) {
  if (!text || !url) {
    return (
      <p>
        <span className="font-medium">{label}:</span>{" "}
        <span className="text-muted-foreground">-</span>
      </p>
    )
  }

  return (
    <p>
      <span className="font-medium">{label}:</span>{" "}
      <a
        href={url}
        target="_blank"
        rel="noreferrer noopener"
        className="underline underline-offset-2 hover:text-foreground"
      >
        {text}
      </a>
    </p>
  )
}

export default async function BlogDetailPage({ params }: BlogDetailPageProps) {
  noStore()

  const { blogId } = await params
  const authorization = await getBackendAuthorizationValue()
  if (!authorization) {
    redirect("/login")
  }

  let payload: BlogDetailResponse | null = null
  try {
    const response = await fetch(
      `${getBackendApiUrl()}/api/blogs/${encodeURIComponent(blogId)}`,
      {
        method: "GET",
        headers: {
          Authorization: authorization,
        },
        cache: "no-store",
      }
    )

    if (!response.ok) {
      notFound()
    }

    payload = (await response.json().catch(() => null)) as BlogDetailResponse | null
  } catch {
    notFound()
  }

  if (!payload?.id) {
    notFound()
  }

  const blog = payload
  const rowData = blog.row_data
  const title = rowData?.klant || "Blog"
  const words = rowData?.woorden || "-"

  return (
    <div className="mx-auto w-full max-w-5xl space-y-6">
      <div className="space-y-2">
        <Link
          href="/dashboard/blogs"
          className="text-sm text-muted-foreground underline underline-offset-4 hover:text-foreground"
        >
          Terug naar alle blogs
        </Link>
        <h1 className="text-3xl font-bold tracking-tight">{title}</h1>
        <p className="text-sm text-muted-foreground">
          {formatCreatedAt(blog.created_at)} · {words} woorden · status:{" "}
          {blog.status}
        </p>
        {blog.published_at && (
          <span className="inline-flex items-center rounded-full bg-green-100 px-2.5 py-0.5 text-xs font-medium text-green-800">
            Gepubliceerd
          </span>
        )}
        <BlogDeleteButton blogId={blog.id} />
      </div>

      <section className="grid gap-3 rounded-lg border bg-card p-5 text-sm md:grid-cols-2">
        <p>
          <span className="font-medium">Bestand:</span> {blog.filename}
        </p>
        <p>
          <span className="font-medium">Onderwerp/Klant:</span>{" "}
          {rowData?.klant || "-"}
        </p>
        <AnchorDisplay
          label="Anker 1"
          text={rowData?.anker_1}
          url={rowData?.anker_1_url}
        />
        <AnchorDisplay
          label="Anker 2"
          text={rowData?.anker_2}
          url={rowData?.anker_2_url}
        />
      </section>

      <BlogEditor blogId={blog.id} initialContent={blog.content} shareToken={blog.share_token} />
      <BlogImagePanel blogId={blog.id} />
      <BlogPublishPanel blogId={blog.id} />
    </div>
  )
}
