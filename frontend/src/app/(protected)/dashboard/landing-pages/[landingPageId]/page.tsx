import Link from "next/link"
import { notFound, redirect } from "next/navigation"
import { unstable_noStore as noStore } from "next/cache"

import { LandingPageEditor } from "@/components/landing-pages/LandingPageEditor"
import { LandingPageDeleteButton } from "@/components/landing-pages/LandingPageDeleteButton"
import {
  getBackendApiUrl,
  getBackendAuthorizationValue,
} from "@/lib/backend-api"
import { type LandingPageDetailPayload } from "@/lib/landing-page-types"

export const metadata = {
  title: "Landingspagina Detail",
}

type LandingPageDetailPageProps = {
  params: Promise<{ landingPageId: string }>
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

export default async function LandingPageDetailPage({ params }: LandingPageDetailPageProps) {
  noStore()

  const { landingPageId } = await params
  const authorization = await getBackendAuthorizationValue()
  if (!authorization) {
    redirect("/login")
  }

  let payload: LandingPageDetailPayload | null = null
  let fetchError: string | null = null
  try {
    const response = await fetch(
      `${getBackendApiUrl()}/api/landing-pages/${encodeURIComponent(landingPageId)}`,
      {
        method: "GET",
        headers: {
          Authorization: authorization,
        },
        cache: "no-store",
      }
    )

    if (response.status === 404) {
      notFound()
    }

    if (!response.ok) {
      fetchError = `Er is een fout opgetreden (${response.status}). Probeer het later opnieuw.`
    } else {
      payload = (await response.json().catch(() => null)) as LandingPageDetailPayload | null
    }
  } catch {
    fetchError = "De pagina kon niet worden geladen. Probeer het later opnieuw."
  }

  if (fetchError) {
    return (
      <div className="mx-auto w-full max-w-5xl space-y-6">
        <Link
          href="/dashboard/landing-pages"
          className="text-sm text-muted-foreground underline underline-offset-4 hover:text-foreground"
        >
          Terug naar alle landingspagina&apos;s
        </Link>
        <p className="text-sm text-destructive">{fetchError}</p>
      </div>
    )
  }

  if (!payload?.id) {
    notFound()
  }

  const landingPage = payload

  return (
    <div className="mx-auto w-full max-w-5xl space-y-6">
      <div className="space-y-2">
        <Link
          href="/dashboard/landing-pages"
          className="text-sm text-muted-foreground underline underline-offset-4 hover:text-foreground"
        >
          Terug naar alle landingspagina&apos;s
        </Link>
        <h1 className="text-3xl font-bold tracking-tight">
          {landingPage.onderwerp || "Landingspagina"}
        </h1>
        <p className="text-sm text-muted-foreground">
          {formatCreatedAt(landingPage.created_at)} · status: {landingPage.status}
        </p>
        {landingPage.is_owner === false && (
          <span className="inline-flex items-center rounded-full bg-blue-100 px-2.5 py-0.5 text-xs font-medium text-blue-800">
            Gedeeld met jou · alleen lezen
          </span>
        )}
        {landingPage.is_owner !== false && (
          <LandingPageDeleteButton landingPageId={landingPage.id} />
        )}
      </div>

      <section className="grid gap-3 rounded-lg border bg-card p-5 text-sm md:grid-cols-2">
        <p>
          <span className="font-medium">Bestand:</span> {landingPage.filename}
        </p>
        <p>
          <span className="font-medium">Onderwerp:</span>{" "}
          {landingPage.onderwerp || "-"}
        </p>
        <p>
          <span className="font-medium">Klant:</span>{" "}
          {landingPage.customer_name || "Geen klant gekoppeld"}
        </p>
      </section>

      <LandingPageEditor
        landingPageId={landingPage.id}
        initialContent={landingPage.content}
        initialMetaTitle={landingPage.meta_title}
        initialMetaDescription={landingPage.meta_description}
        initialSlug={landingPage.slug}
        isOwner={landingPage.is_owner !== false}
        initialIsPublic={landingPage.is_public === true}
        initialCustomerWebsiteId={landingPage.customer_website_id ?? null}
      />
    </div>
  )
}
