// Kaart "Koppelingen voor deze klant" (servercomponent). Alleen-lezen, behalve de Search
// Console-property. Pro Rank Tracker is een trage live-aanroep en WordPress een losse aanroep:
// elk laadt in een eigen Suspense-grens, zodat de rest van de pagina er meteen staat.

import { Suspense } from "react"
import Link from "next/link"
import { Database, Globe, TrendingUp } from "lucide-react"
import type { LucideIcon } from "lucide-react"

import { bareDomain, ResultCard, shortUrl } from "@/components/klanten/analyses/result-parts"
import { SearchConsoleSetting } from "@/components/livegang/SearchConsoleSetting"
import { Skeleton } from "@/components/ui/skeleton"
import { getBackendApiUrl, getBackendAuthorizationValue } from "@/lib/backend-api"
import { fetchCustomerRankings } from "@/lib/customer-api"
import type { CustomerWebsiteDetail } from "@/lib/customer-types"
import type { WordPressSite } from "@/lib/wordpress-types"
import { cn } from "@/lib/utils"

type Status = "connected" | "neutral"

/** Groen bolletje bij gekoppeld, grijs bij neutraal of niet gekoppeld. */
function StatusDot({ status }: { status: Status }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "size-2 shrink-0 rounded-full",
        status === "connected" ? "bg-green-600 dark:bg-green-400" : "bg-muted-foreground/40"
      )}
    />
  )
}

/** Naam van de bron met icoon, zelfde opbouw als in `SearchConsoleSetting`. */
function SourceLabel({ icon: Icon, children }: { icon: LucideIcon; children: React.ReactNode }) {
  return (
    <span className="flex items-center gap-2 font-medium">
      <Icon className="size-4 text-muted-foreground" aria-hidden="true" />
      {children}
    </span>
  )
}

function ConnectionRow({
  icon,
  label,
  status,
  children,
}: {
  icon: LucideIcon
  label: string
  status: Status
  children: React.ReactNode
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <SourceLabel icon={icon}>{label}</SourceLabel>
      <span className="inline-flex min-w-0 items-center gap-2">
        {/* De tekst zegt al of het gekoppeld is; het bolletje is alleen visueel. */}
        <StatusDot status={status} />
        <span className={cn("min-w-0 break-words", status === "neutral" && "text-muted-foreground")}>
          {children}
        </span>
      </span>
    </div>
  )
}

function ConnectionRowSkeleton({ icon, label }: { icon: LucideIcon; label: string }) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1" aria-busy="true">
      <SourceLabel icon={icon}>{label}</SourceLabel>
      <Skeleton className="h-4 w-44" />
      <span className="sr-only">Status laden…</span>
    </div>
  )
}

// --- Pro Rank Tracker -------------------------------------------------------------------------

async function ProRankTrackerRow({ customerId }: { customerId: string }) {
  const rankings = await fetchCustomerRankings(customerId)
  const label = "Pro Rank Tracker"

  if (rankings.state === "ok") {
    const n = rankings.keywords
    return (
      <ConnectionRow icon={TrendingUp} label={label} status="connected">
        Gevolgd · {n.toLocaleString("nl-NL")} {n === 1 ? "zoekwoord" : "zoekwoorden"}
      </ConnectionRow>
    )
  }
  if (rankings.state === "not_tracked") {
    return (
      <ConnectionRow icon={TrendingUp} label={label} status="neutral">
        Site niet gevolgd
      </ConnectionRow>
    )
  }
  return (
    <ConnectionRow icon={TrendingUp} label={label} status="neutral">
      {rankings.message ||
        (rankings.state === "not_configured"
          ? "De koppeling met Pro Rank Tracker is niet ingesteld."
          : "De status kon niet worden opgehaald uit Pro Rank Tracker.")}
    </ConnectionRow>
  )
}

// --- WordPress --------------------------------------------------------------------------------

/** WordPress-sites van de ingelogde medewerker; null bij een fout of zonder autorisatie. */
async function fetchOwnWordPressSites(): Promise<WordPressSite[] | null> {
  const authorization = await getBackendAuthorizationValue()
  if (!authorization) return null
  try {
    const response = await fetch(`${getBackendApiUrl()}/api/wordpress/sites`, {
      method: "GET",
      headers: { Authorization: authorization },
      cache: "no-store",
    })
    if (!response.ok) return null
    const payload = (await response.json().catch(() => null)) as { sites?: unknown } | null
    return Array.isArray(payload?.sites) ? (payload.sites as WordPressSite[]) : null
  } catch {
    return null
  }
}

/** Hoort de site bij deze klant? Zonder `customer_website_ids` (oudere backend) op hostnaam. */
function belongsToCustomer(site: WordPressSite, customer: CustomerWebsiteDetail) {
  if (Array.isArray(site.customer_website_ids)) {
    return site.customer_website_ids.includes(customer.id)
  }
  return bareDomain(site.base_url) === bareDomain(customer.domain || customer.base_url)
}

async function WordPressRow({ customer }: { customer: CustomerWebsiteDetail }) {
  const sites = await fetchOwnWordPressSites()
  const label = "WordPress"

  if (sites === null) {
    return (
      <ConnectionRow icon={Globe} label={label} status="neutral">
        De WordPress-sites konden niet worden opgehaald.
      </ConnectionRow>
    )
  }

  const matches = sites.filter((site) => belongsToCustomer(site, customer))
  const active = matches.filter((site) => site.is_active)
  if (matches.length === 0) {
    return (
      <ConnectionRow icon={Globe} label={label} status="neutral">
        Geen site gekoppeld aan jouw account ·{" "}
        <Link
          href="/dashboard/settings/wordpress"
          className="font-medium text-primary underline-offset-4 hover:underline"
        >
          WordPress sites instellen
        </Link>
      </ConnectionRow>
    )
  }

  const shown = active.length > 0 ? active : matches
  const names = shown.map((site) => `${site.name} (${shortUrl(site.base_url)})`).join(", ")
  return (
    <ConnectionRow icon={Globe} label={label} status={active.length > 0 ? "connected" : "neutral"}>
      {active.length > 0 ? "Gekoppeld aan jouw account" : "Op jouw account, maar uitgeschakeld"} ·{" "}
      {names}
    </ConnectionRow>
  )
}

// --- Kaart ------------------------------------------------------------------------------------

export function KoppelingenCard({ customer }: { customer: CustomerWebsiteDetail }) {
  return (
    <ResultCard
      id="profiel-koppelingen"
      title="Koppelingen voor deze klant"
      description="WordPress-sites zijn per medewerker gekoppeld; de rest geldt voor het hele bureau."
    >
      <ul className="flex flex-col text-sm">
        <li className="border-b pb-3">
          <SearchConsoleSetting customerId={customer.id} />
        </li>
        <li className="border-b py-3">
          <Suspense
            key={`prt-${customer.id}`}
            fallback={<ConnectionRowSkeleton icon={TrendingUp} label="Pro Rank Tracker" />}
          >
            <ProRankTrackerRow customerId={customer.id} />
          </Suspense>
        </li>
        <li className="border-b py-3">
          <Suspense
            key={`wp-${customer.id}`}
            fallback={<ConnectionRowSkeleton icon={Globe} label="WordPress" />}
          >
            <WordPressRow customer={customer} />
          </Suspense>
        </li>
        <li className="pt-3">
          <ConnectionRow icon={Database} label="Ahrefs" status="neutral">
            Geen instelling per klant · gegevens op domein {customer.domain || shortUrl(customer.base_url)}
          </ConnectionRow>
        </li>
      </ul>
    </ResultCard>
  )
}
