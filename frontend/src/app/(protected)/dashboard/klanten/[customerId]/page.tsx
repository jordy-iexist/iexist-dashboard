import Link from "next/link"
import { notFound, redirect } from "next/navigation"
import { unstable_noStore as noStore } from "next/cache"

import { KlantProfielForm } from "@/components/klanten/KlantProfielForm"
import {
  getBackendApiUrl,
  getBackendAuthorizationValue,
} from "@/lib/backend-api"
import { type CustomerWebsiteDetail } from "@/lib/customer-types"

export const metadata = {
  title: "Klant",
}

type KlantDetailPageProps = {
  params: Promise<{ customerId: string }>
}

function StatCard({
  label,
  value,
  hint,
}: {
  label: string
  value: string
  hint?: string
}) {
  return (
    <div className="rounded-lg border bg-card p-4">
      <p className="text-xs font-medium text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-semibold tracking-tight">{value}</p>
      {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
    </div>
  )
}

export default async function KlantDetailPage({ params }: KlantDetailPageProps) {
  noStore()

  const { customerId } = await params
  const authorization = await getBackendAuthorizationValue()
  if (!authorization) {
    redirect("/login")
  }

  let customer: CustomerWebsiteDetail | null = null
  try {
    const response = await fetch(
      `${getBackendApiUrl()}/api/customers/${encodeURIComponent(customerId)}`,
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

    customer = (await response.json().catch(() => null)) as CustomerWebsiteDetail | null
  } catch {
    notFound()
  }

  if (!customer?.id) {
    notFound()
  }

  const target = customer.target_blogs_per_month
  const targetLabel = typeof target === "number" ? String(target) : "—"
  const placedLabel =
    typeof target === "number"
      ? `${customer.placed_this_month} / ${target}`
      : String(customer.placed_this_month)

  return (
    <div className="mx-auto w-full max-w-5xl space-y-6">
      <div className="space-y-2">
        <Link
          href="/dashboard/klanten"
          className="text-sm text-muted-foreground underline underline-offset-4 hover:text-foreground"
        >
          Terug naar klanten
        </Link>
        <h1 className="text-3xl font-bold tracking-tight">{customer.name}</h1>
        <p className="text-sm text-muted-foreground">
          <a
            href={customer.base_url}
            target="_blank"
            rel="noreferrer noopener"
            className="underline underline-offset-2 hover:text-foreground"
          >
            {customer.domain}
          </a>
        </p>
        {!customer.is_active && (
          <span className="inline-flex items-center rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-medium text-amber-800">
            Gedeactiveerd
          </span>
        )}
      </div>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold">Plaatsing van blogs</h2>
        <div className="grid gap-3 sm:grid-cols-3">
          <StatCard label="Blogs per maand (doel)" value={targetLabel} />
          <StatCard
            label="Pending blogs"
            value="—"
            hint="Nog niet beschikbaar (volgt via check blogplaatsing)"
          />
          <StatCard label="Geplaatst deze maand" value={placedLabel} />
        </div>
      </section>

      <KlantProfielForm customer={customer} />
    </div>
  )
}
