/**
 * Catalogus van de vaste analytics-rapporten. Eén `ReportView` rendert elk
 * rapport uit deze config. Labels en eenheden komen uit `metrics` in de
 * API-respons; hier staan alleen keys en groepen.
 */
import { Bot, ClipboardList, Globe, Link2, Search, Wrench, type LucideIcon } from "lucide-react"

/** Vaste lijst metric-keys, of alle metrics van één groep (bijv. dynamische categorieën). */
export type SeriesSpec = string[] | { group: string }

export type ChartKind = "line" | "stacked-bar" | "bar"

export type ChartDef = {
  title: string
  /** Korte uitleg onder de titel. */
  description?: string
  /**
   * `line`: verloop over de metingen (elke reeks dezelfde eenheid, één y-as).
   * `stacked-bar`: delen van een geheel per meting.
   * `bar`: staven naast elkaar per meting; met `latestOnly` een gesorteerde
   * horizontale staaf van alleen de laatste meting.
   */
  kind: ChartKind
  series: SeriesSpec
  /** Vaste y-as, bijv. [0, 100] voor percentages en scores. */
  yDomain?: [number, number]
  /** Y-as omgekeerd: lager is beter (gemiddelde positie). */
  invertY?: boolean
  /** Alleen de laatste meting, als gesorteerde horizontale staaf (`kind: "bar"`). */
  latestOnly?: boolean
  /** Regelset-wissels (`breaks`) markeren in de grafiek. */
  markBreaks?: boolean
  /** Statuskleuren (goed/waarschuwing/fout, in die volgorde) i.p.v. het categorische palet. */
  palette?: "categorical" | "status"
}

export type TableRowSpec = string | { group: string }

export type ReportSection = {
  title: string
  description?: string
  /** Alleen punten van deze fases (standaard die van het rapport). */
  phases?: number[]
  kpis: string[]
  charts: ChartDef[]
  table: TableRowSpec[]
  notes?: string[]
}

export type ReportDef = {
  slug: string
  title: string
  description: string
  icon: LucideIcon
  /** Fases waarvan de punten in dit rapport meetellen (1 = nulmeting, 4 = kwartaalscan). */
  phases: number[]
  kpis: string[]
  charts: ChartDef[]
  table: TableRowSpec[]
  notes?: string[]
  /** Extra blokken onder het hoofdrapport, met eigen fases (bijv. Core Web Vitals). */
  sections?: ReportSection[]
}

export const REPORTS: ReportDef[] = [
  {
    slug: "actiepunten",
    title: "Actiepunten",
    description: "Hoeveel actiepunten elke scan vond, eerlijk vergelijkbaar over regelset-wissels heen, en per categorie.",
    icon: ClipboardList,
    phases: [1, 4],
    kpis: ["issues_comparable", "issues_new_checks"],
    charts: [
      {
        title: "Actiepunten per meting",
        description: "Vergelijkbaar = controles die er bij de oudste meting in deze periode al waren.",
        kind: "stacked-bar",
        series: ["issues_comparable", "issues_new_checks"],
        markBreaks: true,
      },
      {
        title: "Per categorie, laatste meting",
        kind: "bar",
        series: { group: "issues_category" },
        latestOnly: true,
      },
    ],
    table: ["issues_comparable", "issues_new_checks", { group: "issues_category" }],
    notes: [
      "Telt de actiepunten die de scan vond, niet hoeveel er nu nog open staan.",
      "Controles die later zijn toegevoegd tellen als 'nieuwe controles', zodat een nieuwe regelset geen schijnbare verslechtering geeft.",
    ],
  },
  {
    slug: "zichtbaarheid-google",
    title: "Zichtbaarheid in Google",
    description: "Klikken, vertoningen, CTR en gemiddelde positie uit Google Search Console, per kwartaal.",
    icon: Search,
    phases: [4],
    kpis: ["gsc_clicks", "gsc_impressions", "gsc_ctr", "gsc_position", "gsc_indexed_pct"],
    charts: [
      { title: "Klikken", kind: "line", series: ["gsc_clicks"] },
      { title: "Vertoningen", kind: "line", series: ["gsc_impressions"] },
      { title: "CTR", kind: "line", series: ["gsc_ctr"] },
      { title: "Gemiddelde positie", description: "Lager is beter; de as staat daarom omgekeerd.", kind: "line", series: ["gsc_position"], invertY: true },
    ],
    table: [{ group: "gsc" }],
    notes: [
      "Search Console-cijfers gaan over de 90 dagen vóór elke kwartaalscan; vensters van opeenvolgende rondes kunnen overlappen.",
    ],
  },
  {
    slug: "autoriteit",
    title: "Autoriteit & backlinks",
    description: "Domain Rating, verwijzende domeinen en organisch verkeer volgens Ahrefs.",
    icon: Link2,
    phases: [1, 4],
    kpis: ["domain_rating", "refdomains", "backlinks", "org_traffic", "org_keywords", "org_keywords_1_3"],
    charts: [
      { title: "Domain Rating", kind: "line", series: ["domain_rating"], yDomain: [0, 100] },
      { title: "Verwijzende domeinen", kind: "line", series: ["refdomains"] },
      { title: "Organisch verkeer", description: "Geschat maandelijks verkeer volgens Ahrefs.", kind: "line", series: ["org_traffic"] },
    ],
    table: [{ group: "ahrefs" }],
  },
  {
    slug: "ai-vindbaarheid",
    title: "AI-vindbaarheid",
    description: "AI-score en de uitkomst van de AI-checks (toegang voor AI-bots, llms.txt, structuur).",
    icon: Bot,
    phases: [1, 4],
    kpis: ["ai_score", "ai_checks_ok", "ai_checks_warning", "ai_checks_error"],
    charts: [
      { title: "AI-score", kind: "line", series: ["ai_score"], yDomain: [0, 100] },
      {
        title: "AI-checks per uitkomst",
        kind: "stacked-bar",
        series: ["ai_checks_ok", "ai_checks_warning", "ai_checks_error"],
        palette: "status",
      },
    ],
    table: [{ group: "ai" }],
  },
  {
    slug: "techniek",
    title: "Techniek",
    description: "Indexeerbaarheid, foutpagina's, kapotte links en ontbrekende basis-tags; Core Web Vitals uit de nulmeting.",
    icon: Wrench,
    phases: [1, 4],
    kpis: ["pages_total", "indexable_pct", "final_4xx", "broken_link_pages", "avg_response_ms"],
    charts: [
      { title: "Indexeerbare pagina's", kind: "line", series: ["indexable_pct"], yDomain: [0, 100] },
      {
        title: "Technische problemen",
        description: "Aantal pagina's per probleem; één pagina kan meerdere problemen hebben.",
        kind: "bar",
        series: ["final_4xx", "broken_link_pages", "missing_title", "missing_meta", "missing_h1"],
      },
    ],
    table: [{ group: "tech" }],
    sections: [
      {
        title: "Core Web Vitals",
        description: "Alleen gemeten bij de nulmeting (fase 1); kwartaalscans meten dit niet.",
        phases: [1],
        kpis: ["cwv_good_pct", "cwv_poor", "cwv_performance_score"],
        charts: [{ title: "Pagina's met goede Core Web Vitals", kind: "line", series: ["cwv_good_pct"], yDomain: [0, 100] }],
        table: [{ group: "cwv" }],
      },
    ],
  },
  {
    slug: "bing",
    title: "Bing",
    description: "Klikken, vertoningen en pagina's in de index volgens Bing Webmaster Tools, per kwartaal.",
    icon: Globe,
    phases: [4],
    kpis: ["bing_clicks", "bing_impressions", "bing_in_index"],
    charts: [
      { title: "Klikken", kind: "line", series: ["bing_clicks"] },
      { title: "Vertoningen", kind: "line", series: ["bing_impressions"] },
      { title: "Pagina's in de index", kind: "line", series: ["bing_in_index"] },
    ],
    table: [{ group: "bing" }],
  },
]

export function getReport(slug: string): ReportDef | undefined {
  return REPORTS.find((report) => report.slug === slug)
}

export const PHASE_NAMES: Record<number, string> = {
  1: "nulmeting",
  4: "kwartaalscans",
}

export function phasesLabel(phases: number[]): string {
  return phases.map((phase) => PHASE_NAMES[phase] ?? `fase ${phase}`).join(" en ")
}
