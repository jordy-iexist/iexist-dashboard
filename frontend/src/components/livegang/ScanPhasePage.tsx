"use client"

import { ArrowLeft } from "lucide-react"
import Link from "next/link"
import { useRouter, useSearchParams } from "next/navigation"
import { useEffect } from "react"

import { Button } from "@/components/ui/button"
import { ChangesWorkspace } from "@/components/livegang/ChangesWorkspace"
import { ContentWorkspace } from "@/components/livegang/ContentWorkspace"
import { GeoWorkspace } from "@/components/livegang/GeoWorkspace"
import { phaseLockReason, useScanPhases } from "@/components/livegang/LaunchScanWorkspace"
import { MonitorWorkspace } from "@/components/livegang/MonitorWorkspace"
import { NulmetingWorkspace } from "@/components/livegang/NulmetingWorkspace"
import { QuarterlyWorkspace } from "@/components/livegang/QuarterlyWorkspace"
import { PanelRow } from "@/components/livegang/shared"
import {
  SEO_GEO_SECTIONS,
  seoGeoSectionHref,
  seoGeoSlugForPhase,
  type SeoGeoPhase,
  type SeoGeoSlug,
} from "@/lib/seo-geo-sections"

/** Inhoud van één subpagina van de SEO/GEO-scan; de kop staat in de layout. */
export function ScanPhasePage({ slug }: { slug: SeoGeoSlug }) {
  const { customerId, done, outdated, refreshPhases } = useScanPhases()
  const phase = SEO_GEO_SECTIONS.find((section) => section.slug === slug)?.phase ?? null

  // Vorige fase nog niet afgerond: uitleggen waarom, niet stil doorsturen.
  const lockReason = phase === null ? undefined : phaseLockReason(phase, done)
  if (phase !== null && lockReason) {
    const previous = seoGeoSlugForPhase((phase - 1) as SeoGeoPhase)
    const previousTitle = SEO_GEO_SECTIONS.find((section) => section.slug === previous)?.title
    return (
      <PanelRow tone="warning" className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <span className="min-w-0 flex-1">{lockReason}</span>
        <Button size="sm" variant="outline" asChild>
          <Link href={seoGeoSectionHref(customerId, previous)}>
            <ArrowLeft /> Naar fase {phase - 1}: {previousTitle}
          </Link>
        </Button>
      </PanelRow>
    )
  }

  // Fase 2 en 3 bouwen op de nulmeting: melden als er sindsdien een nieuwere nulmeting is.
  const outdatedNotice = phase !== null && outdated[phase] && (
    <PanelRow tone="warning">Deze fase is gebaseerd op een oudere nulmeting. Scan opnieuw om bij te werken.</PanelRow>
  )

  switch (slug) {
    case "nulmeting":
      return <NulmetingWorkspace customerId={customerId} onChange={refreshPhases} />
    case "geo-checklist":
      return (
        <>
          {outdatedNotice}
          <GeoWorkspace customerId={customerId} onChange={refreshPhases} />
        </>
      )
    case "content":
      return (
        <>
          {outdatedNotice}
          <ContentWorkspace customerId={customerId} onChange={refreshPhases} />
        </>
      )
    case "kwartaal":
      return <QuarterlyWorkspace customerId={customerId} onChange={refreshPhases} />
    case "monitor":
      return <MonitorWorkspace customerId={customerId} />
    case "aanpassingen":
      return <ChangesWorkspace customerId={customerId} />
  }
}

/**
 * Adres van de klant zonder onderdeel: door naar de verste gestarte fase, met behoud van de
 * query-string (behalve een onbekende `fase`; bekende waarden stuurt de server al door).
 */
export function ScanIndexRedirect() {
  const { customerId, furthest } = useScanPhases()
  const router = useRouter()
  const searchParams = useSearchParams()

  useEffect(() => {
    const query = new URLSearchParams(searchParams.toString())
    query.delete("fase")
    const search = query.toString()
    router.replace(`${seoGeoSectionHref(customerId, furthest)}${search ? `?${search}` : ""}`)
  }, [customerId, furthest, router, searchParams])

  return null
}
