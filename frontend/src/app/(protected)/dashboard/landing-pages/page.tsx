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
import { LandingPagesBatchList } from "@/components/landing-pages/LandingPagesBatchList"

export const metadata = {
  title: "Alle Landingspagina's",
}

const PAGE_SIZE = 12

type SearchParamsValue = string | string[] | undefined
type LandingPagesPageProps = {
  searchParams?: Promise<Record<string, SearchParamsValue>>
}

type LandingPageScope = "all" | "mine" | "shared"

function parsePageParam(value: SearchParamsValue): number {
  const raw = Array.isArray(value) ? value[0] : value
  const parsed = Number.parseInt(raw ?? "1", 10)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 1
}

function parseScopeParam(value: SearchParamsValue): LandingPageScope {
  const raw = Array.isArray(value) ? value[0] : value
  return raw === "mine" || raw === "shared" ? raw : "all"
}

function buildPageHref(page: number, scope: LandingPageScope) {
  const params = new URLSearchParams()
  if (page > 1) {
    params.set("page", String(page))
  }
  if (scope !== "all") {
    params.set("scope", scope)
  }
  const query = params.toString()
  return query ? `/dashboard/landing-pages?${query}` : "/dashboard/landing-pages"
}

const SCOPE_OPTIONS: { value: LandingPageScope; label: string }[] = [
  { value: "all", label: "Alle" },
  { value: "mine", label: "Van mij" },
  { value: "shared", label: "Gedeeld met mij" },
]

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
  const scope = parseScopeParam(params.scope)
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
    url.searchParams.set("scope", scope)

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

      <div className="flex items-center gap-2">
        {SCOPE_OPTIONS.map((option) => (
          <Link
            key={option.value}
            href={buildPageHref(1, option.value)}
            className={`rounded-full border px-3 py-1.5 text-sm transition-colors ${
              scope === option.value
                ? "border-foreground bg-foreground text-background"
                : "hover:bg-muted"
            }`}
          >
            {option.label}
          </Link>
        ))}
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
                href={buildPageHref(page - 1, scope)}
                label="Vorige"
                disabled={!hasPreviousPage}
              />
              <PaginationLink
                href={buildPageHref(page + 1, scope)}
                label="Volgende"
                disabled={!hasNextPage}
              />
            </div>
          </div>

          <LandingPagesBatchList landingPages={landingPages} />
        </div>
      )}
    </div>
  )
}
