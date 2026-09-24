import Link from "next/link"
import { Pencil, Sheet } from "lucide-react"

import { Button } from "@/components/ui/button"
import { KlantHero } from "@/components/klanten/KlantHero"
import { fetchCustomerDetail } from "@/lib/customer-api"

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
    <div className="py-2 sm:px-6 sm:first:pl-0">
      <p className="text-sm text-muted-foreground">{label}</p>
      <p className="mt-2 text-3xl font-bold tracking-wide text-primary">{value}</p>
      {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
    </div>
  )
}

function ProfileField({
  label,
  className,
  children,
}: {
  label: string
  className?: string
  children: React.ReactNode
}) {
  return (
    <div className={className}>
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="mt-1">{children}</dd>
    </div>
  )
}

function formatDate(value: string | null) {
  if (!value) {
    return null
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return null
  }
  return new Intl.DateTimeFormat("nl-NL", { dateStyle: "medium" }).format(date)
}

function getCustomerStage(since: string | null): "Nieuw" | "Oud" | null {
  if (!since) return null
  const start = new Date(since)
  if (Number.isNaN(start.getTime())) return null
  const cutoff = new Date()
  cutoff.setFullYear(cutoff.getFullYear() - 1)
  return start > cutoff ? "Nieuw" : "Oud"
}

export default async function KlantDetailPage({ params }: KlantDetailPageProps) {
  const { customerId } = await params
  const customer = await fetchCustomerDetail(customerId)

  const target = customer.target_blogs_per_month
  const targetLabel = typeof target === "number" ? String(target) : "—"
  const placedLabel =
    typeof target === "number"
      ? `${customer.placed_this_month} / ${target}`
      : String(customer.placed_this_month)

  const startedLabel = formatDate(customer.seo_customer_since)
  const stage = getCustomerStage(customer.seo_customer_since)

  return (
    <div className="mx-auto w-full max-w-5xl space-y-8">
      <KlantHero eyebrow={customer.category_name} title={customer.name}>
        <a
          href={customer.base_url}
          target="_blank"
          rel="noreferrer noopener"
          className="inline-block text-lg text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
        >
          {customer.domain}
        </a>
        <div className="flex flex-wrap gap-2">
          <Button asChild>
            <Link href={`/dashboard/klanten/${customer.id}/spreadsheet`}>
              <Sheet />
              Open spreadsheet
            </Link>
          </Button>
          <Button asChild variant="outline">
            <Link href={`/dashboard/klanten/${customer.id}/bewerken`}>
              <Pencil />
              Bewerken
            </Link>
          </Button>
        </div>
      </KlantHero>

      <section className="space-y-4">
        <h2 className="text-lg font-bold tracking-wide text-primary">
          Plaatsing van blogs
        </h2>
        <div className="grid gap-2 sm:grid-cols-3 sm:divide-x">
          <StatCard label="Blogs per maand (doel)" value={targetLabel} />
          <StatCard
            label="Pending blogs"
            value="—"
            hint="Nog niet beschikbaar (volgt via check blogplaatsing)"
          />
          <StatCard label="Geplaatst deze maand" value={placedLabel} />
        </div>
      </section>

      <section className="space-y-6 border-t pt-8">
        <h2 className="text-lg font-bold tracking-wide text-primary">
          Klantprofiel
        </h2>
        <dl className="grid gap-x-8 gap-y-5 sm:grid-cols-2">
          <ProfileField label="Site">
            <a
              href={customer.base_url}
              target="_blank"
              rel="noreferrer noopener"
              className="underline-offset-2 hover:underline"
            >
              {customer.base_url}
            </a>
          </ProfileField>
          <ProfileField label="Traject gestart">
            {startedLabel ? `${startedLabel}${stage ? ` · ${stage}` : ""}` : "—"}
          </ProfileField>
          <ProfileField label="Branche / categorie">
            {customer.category_name ?? "—"}
          </ProfileField>
          <ProfileField label="Blogs per maand (doel)">
            {customer.target_blogs_per_month ?? "—"}
          </ProfileField>
          <ProfileField label="Links per maand (doel)">
            {customer.target_links_per_month ?? "—"}
          </ProfileField>
          <ProfileField label="Externe spreadsheet">
            {customer.spreadsheet_url ? (
              <a
                href={customer.spreadsheet_url}
                target="_blank"
                rel="noreferrer noopener"
                className="break-all underline-offset-2 hover:underline"
              >
                {customer.spreadsheet_url}
              </a>
            ) : (
              "—"
            )}
          </ProfileField>
          <ProfileField
            label="Afspraken met klant / SEO-doelstellingen"
            className="sm:col-span-2"
          >
            <p className="whitespace-pre-wrap">{customer.seo_goals || "—"}</p>
          </ProfileField>
        </dl>
      </section>
    </div>
  )
}
