import Link from "next/link"
import { redirect } from "next/navigation"
import { unstable_noStore as noStore } from "next/cache"

import {
  getBackendApiUrl,
  getBackendAuthorizationValue,
  readBackendError,
} from "@/lib/backend-api"
import {
  type LandingPageListItem,
  type LandingPageListResponse,
} from "@/lib/landing-page-types"

export const metadata = {
  title: "Alle Landingspagina's",
}

const PAGE_SIZE = 12

type SearchParamsValue = string | string[] | undefined
type LandingPagesPageProps = {
  searchParams?: Promise<Record<string, SearchParamsValue>>
}

function parsePageParam(value: SearchParamsValue): number {
  const raw = Array.isArray(value) ? value[0] : value
  const parsed = Number.parseInt(raw ?? "1", 10)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 1
}

function buildPageHref(page: number) {
  if (page <= 1) {
    return "/dashboard/landing-pages"
  }
  return `/dashboard/landing-pages?page=${page}`
}

function formatDate(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return "-"
  return new Intl.DateTimeFormat("nl-NL", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date)
}

function statusBadgeClasses(status: string) {
  switch (status) {
    case "pending":
      return "bg-muted text-muted-foreground"
    case "processing":
      return "bg-amber-100 text-amber-800"
    case "completed":
      return "bg-green-100 text-green-800"
    case "failed":
      return "bg-red-100 text-red-800"
    default:
      return "bg-muted text-muted-foreground"
  }
}

function statusLabel(status: string) {
  switch (status) {
    case "pending":
      return "In wachtrij"
    case "processing":
      return "Bezig"
    case "completed":
      return "Voltooid"
    case "failed":
      return "Mislukt"
    default:
      return status
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

export default async function LandingPagesPage({ searchParams }: LandingPagesPageProps) {
  noStore()

  const params = searchParams ? await searchParams : {}
  const page = parsePageParam(params.page)
  const authorization = await getBackendAuthorizationValue()
  if (!authorization) {
    redirect("/login")
  }

  let landingPages: LandingPageListItem[] = []
  let total = 0
  let errorMessage: string | null = null

  try {
    const url = new URL(`${getBackendApiUrl()}/api/landing-pages`)
    url.searchParams.set("page", String(page))
    url.searchParams.set("page_size", String(PAGE_SIZE))

    const response = await fetch(url, {
      method: "GET",
      headers: {
        Authorization: authorization,
      },
      cache: "no-store",
    })

    if (!response.ok) {
      errorMessage = await readBackendError(response, "Kon landingspagina's niet ophalen.")
    } else {
      const payload = (await response.json().catch(() => null)) as
        | LandingPageListResponse
        | null
      const items = Array.isArray(payload?.landing_pages) ? payload.landing_pages : []
      total = typeof payload?.total === "number" ? payload.total : items.length
      landingPages = items
    }
  } catch (error) {
    const details = error instanceof Error ? error.message : "Backend verbinding mislukt."
    errorMessage = `Kon landingspagina's niet ophalen. Details: ${details}`
  }

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const hasPreviousPage = page > 1
  const hasNextPage = page < totalPages

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Alle Landingspagina&apos;s</h1>
          <p className="text-muted-foreground">
            Bekijk alle gegenereerde landingspagina&apos;s
          </p>
        </div>
        <Link
          href="/dashboard/landing-pages/upload"
          className="shrink-0 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
          Nieuwe upload
        </Link>
      </div>

      {errorMessage && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {errorMessage}
        </div>
      )}

      {!errorMessage && landingPages.length === 0 && (
        <div className="rounded-lg border p-8 text-center">
          <p className="text-muted-foreground">
            Nog geen landingspagina&apos;s beschikbaar. Upload een CSV bestand om te starten.
          </p>
        </div>
      )}

      {!errorMessage && landingPages.length > 0 && (
        <div className="space-y-4">
          <div className="flex items-center justify-between gap-4">
            <p className="text-sm text-muted-foreground">
              Pagina {page} van {totalPages} · {total} landingspagina
              {total === 1 ? "" : "'s"}
            </p>
            <div className="flex items-center gap-2">
              <PaginationLink
                href={buildPageHref(page - 1)}
                label="Vorige"
                disabled={!hasPreviousPage}
              />
              <PaginationLink
                href={buildPageHref(page + 1)}
                label="Volgende"
                disabled={!hasNextPage}
              />
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {landingPages.map((item) => (
              <Link
                key={item.id}
                href={`/dashboard/landing-pages/${item.id}`}
                className="rounded-lg border bg-card p-4 space-y-2 transition-colors hover:bg-muted/50"
              >
                <div className="flex items-start justify-between gap-2">
                  <p className="font-medium text-sm leading-snug line-clamp-2">
                    {item.onderwerp || "Onbekend onderwerp"}
                  </p>
                  <span
                    className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ${statusBadgeClasses(item.status)}`}
                  >
                    {statusLabel(item.status)}
                  </span>
                </div>
                {item.meta_title && (
                  <p className="text-xs text-muted-foreground line-clamp-1">
                    {item.meta_title}
                  </p>
                )}
                <div className="text-xs text-muted-foreground space-y-0.5">
                  <p className="truncate">{item.filename}</p>
                  <p>{formatDate(item.created_at)}</p>
                </div>
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
