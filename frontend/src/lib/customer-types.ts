export type CustomerWebsiteItem = {
  id: string
  name: string
  base_url: string
  domain: string
  seo_customer_since: string | null
  seo_goals: string | null
  /** Tone of voice voor teksten; de content brief volgt dit letterlijk. */
  tone_of_voice: string | null
  /** Aanspreekvorm in teksten; null = niet vastgelegd. */
  form_of_address: "je" | "u" | null
  category_id: string | null
  category_name: string | null
  target_blogs_per_month: number | null
  target_links_per_month: number | null
  spreadsheet_url: string | null
  created_by: string
  created_at: string
  updated_at: string
}

/** Dienst met prijs uit het klantprofiel; Claude noemt alleen deze bedragen. */
export type CustomerService = {
  name: string
  price: string
}

/**
 * Klantprofiel: feiten, bewijs en schrijfregels die met de content brief en de
 * concepttekst aan Claude worden meegegeven. Lege strings en lege lijsten = niet ingevuld.
 * Naam, website, toon en aanspreekvorm staan niet hierin maar op de klant zelf.
 */
export type CustomerProfile = {
  company_type: string
  service_area: string
  target_audience: string
  specialties: string
  services: CustomerService[]
  /** Waar de prijzen vandaan komen, bijv. "prijslijst 2026". */
  services_source: string
  usps: string[]
  reviews: string
  certifications: string
  team: string
  /** Cases die met toestemming van de klant genoemd mogen worden. */
  cases: string[]
  language_level: string
  fixed_cta: string
  /** Alleen bewaard en getoond; gaan niet naar Claude. */
  example_urls: string[]
  avoid_words: string[]
  content_rules: string[]
}

export type CustomerWebsiteDetail = CustomerWebsiteItem & {
  placed_this_month: number
  links_placed_this_month: number
  pending_blogs: number | null
  /** Ontbreekt bij een oudere backend; behandel dat als een leeg profiel. */
  profile?: CustomerProfile | null
}

export type CustomerWebsiteListItem = CustomerWebsiteItem & {
  placed_this_month: number
  links_placed_this_month: number
}

export type CustomersResponse = {
  websites: CustomerWebsiteListItem[]
}

export type CustomerCategory = {
  id: string
  name: string
  customer_count: number
}

export type CustomerCategoriesResponse = {
  categories: CustomerCategory[]
}

export type CustomerRankingsState =
  | "ok"
  | "not_configured"
  | "not_tracked"
  | "error"

// Antwoord van GET /api/customers/{id}/rankings (live uit Pro Rank Tracker).
export type CustomerRankings = {
  state: CustomerRankingsState
  message: string | null
  fetched_at: string | null
  /** Gevolgde zoekwoorden. */
  keywords: number
  /** Zoekwoorden met een positie in de top 100. */
  ranked: number
  avg_position: number | null
  /** Positief = verbeterd t.o.v. een maand geleden. */
  avg_position_delta: number | null
  top3: number
  top3_delta: number | null
  /** Gevolgde zoekwoorden met volume zonder positie in de top 100 (hoogste volume eerst, afgekapt). */
  content_gaps: CustomerContentGap[]
  /** Totaal aantal van die zoekwoorden, ook de niet getoonde. */
  content_gaps_total: number
}

export type CustomerContentGap = {
  keyword: string
  volume: number
}

export type CustomerQuickWinsState = "ok" | "not_configured" | "error"

export type QuickWinChance = "hoog" | "middel" | "laag"

export type QuickWinSource = "prt" | "ahrefs" | "both"

export type CustomerQuickWinRow = {
  keyword: string
  position: number
  /** Positief = gestegen t.o.v. 30 dagen geleden. */
  delta: number | null
  volume: number | null
  kd: number | null
  url: string | null
  kans: QuickWinChance
  /** Waar de rij vandaan komt: gevolgd in Pro Rank Tracker, gevonden door Ahrefs, of beide. */
  source: QuickWinSource
}

// Antwoord van GET /api/customers/{id}/quick-wins en POST …/quick-wins/refresh
// (bewaarde stand uit Ahrefs).
export type CustomerQuickWins = {
  state: CustomerQuickWinsState
  /** Waarschuwing of foutmelding; kan ook bij "ok" gevuld zijn (oude stand getoond). */
  message: string | null
  fetched_at: string | null
  /** Maximaal aantal rijen. */
  limit: number
  /** `true` als er precies `limit` rijen zijn. */
  capped: boolean
  /** Positie 4–20, aflopend op zoekvolume. */
  rows: CustomerQuickWinRow[]
}

// Open verbeterpunten uit het scherm Aanpassingen.
export type CustomerImprovements = {
  open: number
  openHigh: number
  hasSources: boolean
}
