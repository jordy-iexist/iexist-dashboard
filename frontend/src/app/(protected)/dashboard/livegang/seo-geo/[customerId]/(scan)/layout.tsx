import Link from "next/link"
import { ArrowLeft, ExternalLink } from "lucide-react"

import { LaunchScanWorkspace } from "@/components/livegang/LaunchScanWorkspace"
import { fetchCustomerDetail } from "@/lib/customer-api"

type SeoGeoScanLayoutProps = {
  children: React.ReactNode
  params: Promise<{ customerId: string }>
}

/**
 * Kop van de SEO/GEO-scan van een klant rond de subpagina's (fases, Monitor, Aanpassingen). In een route group, zodat de printpagina van de checklist erbuiten valt.
 */
export default async function SeoGeoScanLayout({ children, params }: SeoGeoScanLayoutProps) {
  const { customerId } = await params
  const customer = await fetchCustomerDetail(customerId)

  return (
    <LaunchScanWorkspace
      customerId={customer.id}
      header={
        <>
          <Link
            href="/dashboard/livegang/seo-geo"
            className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="size-4" />
            SEO/GEO-scan
          </Link>
          <div className="space-y-0.5">
            <h1 className="text-2xl font-bold tracking-tight text-primary sm:text-3xl">{customer.name}</h1>
            <a
              href={customer.base_url}
              target="_blank"
              rel="noreferrer noopener"
              className="inline-flex items-center gap-1 text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
            >
              {customer.domain}
              <ExternalLink className="size-3.5" />
            </a>
          </div>
        </>
      }
    >
      {children}
    </LaunchScanWorkspace>
  )
}
