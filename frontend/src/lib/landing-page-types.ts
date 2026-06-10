export const LANDING_PAGE_FIELDS = [
  "website",
  "onderwerp",
  "lengte",
  "primaire_zoekwoorden",
  "secundaire_zoekwoorden",
] as const

export const DEFAULT_LANDING_PAGE_PROMPT_TEMPLATE =
  "Opdracht: Schrijf een informatieve SEO-geoptimaliseerde landingspagina van minimaal {lengte} woorden voor de website {website}.\n" +
  "\n" +
  "Het onderwerp van de landingspagina is: {onderwerp}.\n" +
  "\n" +
  "Doel van de landingspagina: bezoekers informeren en aanzetten tot het doen van een offerte aanvraag. Benoem duidelijk hoe {website} de bezoeker kan helpen.\n" +
  "\n" +
  "Stijl:\n" +
  "\n" +
  "Gebruik duidelijke, korte zinnen.\n" +
  "\n" +
  "Gebruik actieve taal (geen \"er wordt gekeken naar…\" maar \"de bank kijkt naar…\").\n" +
  "\n" +
  "Gebruik H2- en H3-tussenkoppen met zoekwoorden erin verwerkt. Verwerk de H2 en H3 tussenkoppen met opmaak, dus niet als H2: en H3:.\n" +
  "\n" +
  "Gebruik maximaal 1 opsomming in de pagina.\n" +
  "\n" +
  "Sluit af met een korte samenvatting en een call-to-action naar {website}.\n" +
  "\n" +
  "SEO-richtlijnen:\n" +
  "\n" +
  "Gebruik de primaire zoekwoorden elk minimaal 2–3 keer, verspreid over de tekst en in minstens één tussenkop:\n" +
  "\n" +
  "{primaire_zoekwoorden}\n" +
  "\n" +
  "Gebruik de secundaire zoekwoorden minimaal één keer, verspreid over de tekst:\n" +
  "\n" +
  "{secundaire_zoekwoorden}\n" +
  "\n" +
  "Structuur van de pagina:\n" +
  "\n" +
  "Titel met hoofdzoekwoord.\n" +
  "\n" +
  "Introductie: kort, pakkend, en met het hoofdzoekwoord in de eerste alinea.\n" +
  "\n" +
  "Informatieve hoofdsecties (H2's):\n" +
  "\n" +
  "Beantwoord de belangrijkste vragen van de doelgroep over het onderwerp.\n" +
  "\n" +
  "FAQ-sectie:\n" +
  "\n" +
  "Voeg 6 relevante veelgestelde vragen en antwoorden toe.\n" +
  "\n" +
  "Antwoorden zijn kort (50–100 woorden) en informatief.\n" +
  "\n" +
  "FAQ's moeten aansluiten bij het onderwerp en long-tail zoektermen bevatten."

export type LandingPageField = (typeof LANDING_PAGE_FIELDS)[number]

export const LANDING_PAGE_FIELD_LABELS: Record<LandingPageField, string> = {
  website: "Website",
  onderwerp: "Onderwerp",
  lengte: "Lengte (woorden)",
  primaire_zoekwoorden: "Primaire zoekwoorden",
  secundaire_zoekwoorden: "Secundaire zoekwoorden",
}

export type LandingPageRowData = {
  website?: string
  onderwerp?: string
  lengte?: string
  primaire_zoekwoorden?: string
  secundaire_zoekwoorden?: string
}

export type LandingPageListItem = {
  id: string
  meta_title: string | null
  onderwerp: string
  filename: string
  status: string
  created_at: string
  is_public?: boolean
  is_owner?: boolean
}

export type LandingPageListResponse = {
  landing_pages: LandingPageListItem[]
  total: number
  page: number
  page_size: number
}

export type LandingPageDetailPayload = {
  id: string
  content: string
  meta_title: string | null
  meta_description: string | null
  slug: string | null
  share_token: string
  status: string
  onderwerp: string
  filename: string
  created_at: string
  is_public?: boolean
  is_owner?: boolean
}

export type LandingPageUploadResponse = {
  upload_id: string
  rows_count: number
  jobs_queued: number
  skipped_rows: number
  status: string
}

export type LandingPageRecentUploadItem = {
  upload_id: string
  filename: string
  created_at: string
  total_jobs: number
  completed: number
  failed: number
  canceled: number
  processed: number
  is_done: boolean
  final_status: "processing" | "completed" | "completed_with_errors" | "canceled"
}

export type LandingPageRecentUploadsResponse = {
  uploads: LandingPageRecentUploadItem[]
}

export type LandingPageUploadStatus = {
  upload_id: string
  filename: string
  total_jobs: number
  completed: number
  failed: number
  processing: number
  pending: number
  canceled: number
  processed: number
  remaining: number
  skipped_rows: number
  is_done: boolean
  final_status: "processing" | "completed" | "completed_with_errors" | "canceled"
}

export type LandingPageGenerationSettings = {
  system_prompt: string | null
  reasoning_effort: string | null
  model: string | null
  max_output_tokens: number | null
  effective_system_prompt: string
  effective_reasoning_effort: string
  effective_model: string
  effective_max_output_tokens: number
}
