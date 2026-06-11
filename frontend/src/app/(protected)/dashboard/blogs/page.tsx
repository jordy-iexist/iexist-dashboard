import Link from "next/link"
import { redirect } from "next/navigation"
import { unstable_noStore as noStore } from "next/cache"

import {
  BlogsBatchPublishList,
  type BlogListItem,
} from "@/components/blogs/BlogsBatchPublishList"
import {
  CustomerFilterSelect,
  type CustomerFilterOption,
} from "@/components/klanten/CustomerFilterSelect"
import { type CustomersResponse } from "@/lib/customer-types"
import {
  getBackendApiUrl,
  getBackendAuthorizationValue,
  readBackendError,
} from "@/lib/backend-api"
import {
  type BlogPublicationSummary,
  type BlogRowData,
  type BlogsListResponse,
} from "@/lib/blog-types"

export const metadata = {
  title: "Alle Blogs",
}

const PAGE_SIZE = 12
const EMPTY_PUBLICATION_SUMMARY: BlogPublicationSummary = {
  total: 0,
  succeeded: 0,
  failed: 0,
  pending: 0,
  processing: 0,
}

type SearchParamsValue = string | string[] | undefined
type BlogsPageProps = {
  searchParams?: Promise<Record<string, SearchParamsValue>>
}

type BlogScope = "all" | "mine" | "shared"

function parsePageParam(value: SearchParamsValue): number {
  const raw = Array.isArray(value) ? value[0] : value
  const parsed = Number.parseInt(raw ?? "1", 10)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 1
}

function parseScopeParam(value: SearchParamsValue): BlogScope {
  const raw = Array.isArray(value) ? value[0] : value
  return raw === "mine" || raw === "shared" ? raw : "all"
}

function parseCustomerParam(value: SearchParamsValue): string | null {
  const raw = Array.isArray(value) ? value[0] : value
  const trimmed = raw?.trim() ?? ""
  return trimmed.length > 0 ? trimmed : null
}

function buildPageHref(page: number, scope: BlogScope, customer: string | null) {
  const params = new URLSearchParams()
  if (page > 1) {
    params.set("page", String(page))
  }
  if (scope !== "all") {
    params.set("scope", scope)
  }
  if (customer) {
    params.set("customer_website_id", customer)
  }
  const query = params.toString()
  return query ? `/dashboard/blogs?${query}` : "/dashboard/blogs"
}

const SCOPE_OPTIONS: { value: BlogScope; label: string }[] = [
  { value: "all", label: "Alle" },
  { value: "mine", label: "Van mij" },
  { value: "shared", label: "Gedeeld met mij" },
]

function toText(value: unknown, fallback = "-") {
  if (typeof value !== "string") {
    return fallback
  }
  const trimmed = value.trim()
  return trimmed.length > 0 ? trimmed : fallback
}

function buildPreview(content: string, maxLength = 220) {
  const normalized = content.replace(/\s+/g, " ").trim()
  if (normalized.length <= maxLength) {
    return normalized
  }
  return `${normalized.slice(0, maxLength).trimEnd()}...`
}

function normalizePublicationSummary(
  value: BlogPublicationSummary | null | undefined
): BlogPublicationSummary {
  if (!value) {
    return EMPTY_PUBLICATION_SUMMARY
  }

  return {
    total: typeof value.total === "number" ? value.total : 0,
    succeeded: typeof value.succeeded === "number" ? value.succeeded : 0,
    failed: typeof value.failed === "number" ? value.failed : 0,
    pending: typeof value.pending === "number" ? value.pending : 0,
    processing: typeof value.processing === "number" ? value.processing : 0,
  }
}

function mapBlogListItem(blog: {
  id: string
  row_data: BlogRowData | null
  content: string
  created_at: string
  filename: string
  published_at?: string | null
  publication?: BlogPublicationSummary | null
  share_token: string
  is_public?: boolean
  is_owner?: boolean
  customer_website_id?: string | null
  customer_name?: string | null
}): BlogListItem {
  const rowData = blog.row_data ?? {}
  return {
    id: blog.id,
    shareToken: blog.share_token,
    title: toText(rowData.klant, "Onbekend onderwerp"),
    createdAt: blog.created_at,
    filename: toText(blog.filename, "Onbekend bestand"),
    words: toText(rowData.woorden),
    anchor1: toText(rowData.anker_1),
    anchor2: toText(rowData.anker_2),
    preview: buildPreview(blog.content),
    publication: normalizePublicationSummary(blog.publication),
    published_at: blog.published_at ?? null,
    isPublic: blog.is_public ?? false,
    isOwner: blog.is_owner ?? true,
    customerName: blog.customer_name ?? null,
  }
}

function PaginationLink({
  href,
  label,
  disabled,
}: {
  href: string
  label: string
  disabled: boolean
}) {
  if (disabled) {
    return (
      <span className="rounded-md border px-3 py-1.5 text-sm text-muted-foreground">
        {label}
      </span>
    )
  }

  return (
    <Link
      href={href}
      className="rounded-md border px-3 py-1.5 text-sm transition-colors hover:bg-muted"
    >
      {label}
    </Link>
  )
}

export default async function BlogsPage({ searchParams }: BlogsPageProps) {
  noStore()

  const params = searchParams ? await searchParams : {}
  const page = parsePageParam(params.page)
  const scope = parseScopeParam(params.scope)
  const customerFilter = parseCustomerParam(params.customer_website_id)
  const authorization = await getBackendAuthorizationValue()
  if (!authorization) {
    redirect("/login")
  }

  let blogs: BlogListItem[] = []
  let totalBlogs = 0
  let errorMessage: string | null = null
  let customers: CustomerFilterOption[] = []

  try {
    const customersResponse = await fetch(
      `${getBackendApiUrl()}/api/customers?active_only=true`,
      {
        method: "GET",
        headers: { Authorization: authorization },
        cache: "no-store",
      }
    )
    if (customersResponse.ok) {
      const payload = (await customersResponse.json().catch(() => null)) as
        | CustomersResponse
        | null
      customers = (payload?.websites ?? []).map((customer) => ({
        id: customer.id,
        name: customer.name,
      }))
    }
  } catch {
    // Klantfilter is niet kritiek voor de pagina; lijst blijft leeg.
  }

  try {
    const url = new URL(`${getBackendApiUrl()}/api/blogs`)
    url.searchParams.set("page", String(page))
    url.searchParams.set("page_size", String(PAGE_SIZE))
    url.searchParams.set("scope", scope)
    if (customerFilter) {
      url.searchParams.set("customer_website_id", customerFilter)
    }

    const response = await fetch(url, {
      method: "GET",
      headers: {
        Authorization: authorization,
      },
      cache: "no-store",
    })

    if (!response.ok) {
      errorMessage = await readBackendError(
        response,
        "Kon blogs niet ophalen."
      )
    } else {
      const payload = (await response.json().catch(() => null)) as
        | BlogsListResponse
        | null
      const items = Array.isArray(payload?.blogs) ? payload.blogs : []
      totalBlogs = typeof payload?.total === "number" ? payload.total : items.length
      blogs = items.map(mapBlogListItem)
    }
  } catch (error) {
    const details =
      error instanceof Error ? error.message : "Backend verbinding mislukt."
    errorMessage = `Kon blogs niet ophalen. Details: ${details}`
  }

  const totalPages = Math.max(1, Math.ceil(totalBlogs / PAGE_SIZE))
  const hasPreviousPage = page > 1
  const hasNextPage = page < totalPages

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Alle Blogs</h1>
        <p className="text-muted-foreground">
          Bekijk alle gegenereerde blogs vanuit de backend
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {SCOPE_OPTIONS.map((option) => (
          <Link
            key={option.value}
            href={buildPageHref(1, option.value, customerFilter)}
            className={`rounded-full border px-3 py-1.5 text-sm transition-colors ${
              scope === option.value
                ? "border-foreground bg-foreground text-background"
                : "hover:bg-muted"
            }`}
          >
            {option.label}
          </Link>
        ))}
        <div className="ml-auto">
          <CustomerFilterSelect
            customers={customers}
            selected={customerFilter}
            scope={scope}
            basePath="/dashboard/blogs"
          />
        </div>
      </div>

      {errorMessage && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {errorMessage}
        </div>
      )}

      {!errorMessage && blogs.length === 0 && (
        <div className="rounded-lg border p-8 text-center">
          <p className="text-muted-foreground">
            Nog geen blogs beschikbaar. Upload een CSV bestand om te starten.
          </p>
        </div>
      )}

      {!errorMessage && blogs.length > 0 && (
        <div className="space-y-4">
          <div className="flex items-center justify-between gap-4">
            <p className="text-sm text-muted-foreground">
              Pagina {page} van {totalPages} · {totalBlogs} blog
              {totalBlogs === 1 ? "" : "s"}
            </p>
            <div className="flex items-center gap-2">
              <PaginationLink
                href={buildPageHref(page - 1, scope, customerFilter)}
                label="Vorige"
                disabled={!hasPreviousPage}
              />
              <PaginationLink
                href={buildPageHref(page + 1, scope, customerFilter)}
                label="Volgende"
                disabled={!hasNextPage}
              />
            </div>
          </div>

          <BlogsBatchPublishList blogs={blogs} />
        </div>
      )}
    </div>
  )
}
