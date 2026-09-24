import { notFound, redirect } from "next/navigation"
import { unstable_noStore as noStore } from "next/cache"

import { BlogDeleteButton } from "@/components/blogs/BlogDeleteButton"
import { BlogEditor } from "@/components/blogs/BlogEditor"
import { BlogImagePanel } from "@/components/blogs/BlogImagePanel"
import { BlogPublishPanel } from "@/components/blogs/BlogPublishPanel"
import { KlantHero } from "@/components/klanten/KlantHero"
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

function DetailItem({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <div className="min-w-0 space-y-0.5">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="break-words font-medium">{children}</dd>
    </div>
  )
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
  return (
    <DetailItem label={label}>
      {text && url ? (
        <a
          href={url}
          target="_blank"
          rel="noreferrer noopener"
          className="underline underline-offset-2 hover:text-primary"
        >
          {text}
        </a>
      ) : (
        <span className="text-muted-foreground">-</span>
      )}
    </DetailItem>
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
    <div className="mx-auto w-full max-w-5xl space-y-8">
      <KlantHero
        backHref="/dashboard/blogs"
        backLabel="Terug naar alle blogs"
        eyebrow={blog.customer_name}
        title={title}
      >
        <p className="text-muted-foreground">
          {formatCreatedAt(blog.created_at)} · {words} woorden · status:{" "}
          {blog.status}
        </p>
        {(blog.published_at || blog.is_owner === false) && (
          <div className="flex flex-wrap gap-2">
            {blog.published_at && (
              <span className="inline-flex items-center rounded-full bg-green-100 px-2.5 py-0.5 text-xs font-medium text-green-800 dark:bg-green-900/30 dark:text-green-300">
                Gepubliceerd
              </span>
            )}
            {blog.is_owner === false && (
              <span className="inline-flex items-center rounded-full bg-blue-100 px-2.5 py-0.5 text-xs font-medium text-blue-800 dark:bg-blue-900/30 dark:text-blue-300">
                Gedeeld met jou · alleen lezen
              </span>
            )}
          </div>
        )}
        <dl className="grid gap-x-8 gap-y-3 text-sm sm:grid-cols-2 lg:grid-cols-3">
          <DetailItem label="Bestand">{blog.filename}</DetailItem>
          <DetailItem label="Onderwerp/Klant">{rowData?.klant || "-"}</DetailItem>
          <DetailItem label="Klant">
            {blog.customer_name || "Geen klant gekoppeld"}
          </DetailItem>
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
        </dl>
        {blog.is_owner !== false && <BlogDeleteButton blogId={blog.id} />}
      </KlantHero>

      <BlogEditor
        blogId={blog.id}
        initialContent={blog.content}
        shareToken={blog.share_token}
        isOwner={blog.is_owner !== false}
        initialIsPublic={blog.is_public === true}
        initialCustomerWebsiteId={blog.customer_website_id ?? null}
      />
      {blog.is_owner !== false && (
        <>
          <hr className="border-t-2 border-foreground/15" />
          <div className="panel-iexist divide-y divide-foreground/10">
            <BlogImagePanel blogId={blog.id} />
            <BlogPublishPanel blogId={blog.id} />
          </div>
        </>
      )}
    </div>
  )
}
