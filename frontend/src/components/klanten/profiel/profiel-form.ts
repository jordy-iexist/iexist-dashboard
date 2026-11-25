// Formulierstate van de pagina Klantprofiel: omzetten van de klant naar het formulier en
// terug naar de PATCH-body, met dezelfde opschoning en limieten als de backend.

import type {
  CustomerProfile,
  CustomerService,
  CustomerWebsiteDetail,
} from "@/lib/customer-types"

/** Limieten waarop de backend afkapt; de invoer houdt zich er ook aan. */
export const LIMITS = {
  /** Vrije tekstvelden van het profiel. */
  text: 300,
  /** USP's, cases en regels voor AI-content. */
  listItems: 30,
  listItem: 300,
  exampleUrls: 10,
  exampleUrl: 500,
  avoidWords: 60,
  avoidWord: 60,
  services: 40,
  /** Naam en prijs van een dienst. */
  serviceField: 120,
} as const

export type FormOfAddress = "" | "je" | "u"

/** Eén dienst in het formulier; `key` houdt de rij stabiel bij toevoegen en verwijderen. */
export type ServiceRow = CustomerService & { key: string }

export type ProfielForm = {
  // Velden op de klant zelf
  name: string
  baseUrl: string
  seoCustomerSince: string
  seoGoals: string
  toneOfVoice: string
  formOfAddress: FormOfAddress
  categoryId: string
  targetBlogsPerMonth: string
  targetLinksPerMonth: string
  spreadsheetUrl: string
  // Profiel
  companyType: string
  serviceArea: string
  targetAudience: string
  specialties: string
  services: ServiceRow[]
  servicesSource: string
  /** Lijsten staan als tekst met één item per regel, zodat typen niet verspringt. */
  usps: string
  reviews: string
  certifications: string
  team: string
  cases: string
  languageLevel: string
  fixedCta: string
  exampleUrls: string
  /** Eén woord per regel of gescheiden door komma's. */
  avoidWords: string
  contentRules: string
}

export type UpdateField = <K extends keyof ProfielForm>(key: K, value: ProfielForm[K]) => void

/** Kaarten die in bewerkstand kunnen staan. */
export type CardId =
  | "bedrijf"
  | "diensten"
  | "usps"
  | "bewijs"
  | "tone"
  | "regels"
  | "traject"

/** Wat elke bewerkbare kaart meekrijgt. */
export type CardProps = {
  form: ProfielForm
  update: UpdateField
  editing: boolean
  onToggle: () => void
  disabled: boolean
}

// --- Profiel uit het antwoord -----------------------------------------------------------------

export function emptyProfile(): CustomerProfile {
  return {
    company_type: "",
    service_area: "",
    target_audience: "",
    specialties: "",
    services: [],
    services_source: "",
    usps: [],
    reviews: "",
    certifications: "",
    team: "",
    cases: [],
    language_level: "",
    fixed_cta: "",
    example_urls: [],
    avoid_words: [],
    content_rules: [],
  }
}

function text(value: unknown): string {
  return typeof value === "string" ? value : ""
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : []
}

function services(value: unknown): CustomerService[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((item) => {
    if (!item || typeof item !== "object") return []
    const { name, price } = item as Record<string, unknown>
    return [{ name: text(name), price: text(price) }]
  })
}

/** Profiel uit het antwoord van de backend; ontbreekt het (oudere backend), dan een leeg profiel. */
export function parseProfile(raw: unknown): CustomerProfile {
  if (!raw || typeof raw !== "object") return emptyProfile()
  const p = raw as Record<string, unknown>
  return {
    company_type: text(p.company_type),
    service_area: text(p.service_area),
    target_audience: text(p.target_audience),
    specialties: text(p.specialties),
    services: services(p.services),
    services_source: text(p.services_source),
    usps: strings(p.usps),
    reviews: text(p.reviews),
    certifications: text(p.certifications),
    team: text(p.team),
    cases: strings(p.cases),
    language_level: text(p.language_level),
    fixed_cta: text(p.fixed_cta),
    example_urls: strings(p.example_urls),
    avoid_words: strings(p.avoid_words),
    content_rules: strings(p.content_rules),
  }
}

// --- Klant → formulier ------------------------------------------------------------------------

let serviceKeyCounter = 0

/** Nieuwe, lege dienstrij. */
export function newServiceRow(service: CustomerService = { name: "", price: "" }): ServiceRow {
  serviceKeyCounter += 1
  return { ...service, key: `dienst-${serviceKeyCounter}` }
}

function countToText(value: number | null | undefined) {
  return typeof value === "number" ? String(value) : ""
}

export function toForm(customer: CustomerWebsiteDetail): ProfielForm {
  const profile = parseProfile(customer.profile)
  return {
    name: customer.name,
    baseUrl: customer.base_url,
    seoCustomerSince: customer.seo_customer_since ?? "",
    seoGoals: customer.seo_goals ?? "",
    toneOfVoice: customer.tone_of_voice ?? "",
    formOfAddress: customer.form_of_address ?? "",
    categoryId: customer.category_id ?? "",
    targetBlogsPerMonth: countToText(customer.target_blogs_per_month),
    targetLinksPerMonth: countToText(customer.target_links_per_month),
    spreadsheetUrl: customer.spreadsheet_url ?? "",
    companyType: profile.company_type,
    serviceArea: profile.service_area,
    targetAudience: profile.target_audience,
    specialties: profile.specialties,
    services: profile.services.map((service) => newServiceRow(service)),
    servicesSource: profile.services_source,
    usps: profile.usps.join("\n"),
    reviews: profile.reviews,
    certifications: profile.certifications,
    team: profile.team,
    cases: profile.cases.join("\n"),
    languageLevel: profile.language_level,
    fixedCta: profile.fixed_cta,
    exampleUrls: profile.example_urls.join("\n"),
    avoidWords: profile.avoid_words.join("\n"),
    contentRules: profile.content_rules.join("\n"),
  }
}

/** Leeg formulier voor een nieuwe klant. */
export function emptyForm(): ProfielForm {
  return {
    name: "",
    baseUrl: "",
    seoCustomerSince: "",
    seoGoals: "",
    toneOfVoice: "",
    formOfAddress: "",
    categoryId: "",
    targetBlogsPerMonth: "",
    targetLinksPerMonth: "",
    spreadsheetUrl: "",
    companyType: "",
    serviceArea: "",
    targetAudience: "",
    specialties: "",
    services: [],
    servicesSource: "",
    usps: "",
    reviews: "",
    certifications: "",
    team: "",
    cases: "",
    languageLevel: "",
    fixedCta: "",
    exampleUrls: "",
    avoidWords: "",
    contentRules: "",
  }
}

// --- Opschonen --------------------------------------------------------------------------------

function clip(value: string, max: number) {
  return value.trim().slice(0, max).trim()
}

/** Lege items en dubbelen (hoofdletterongevoelig) weg, de rest afgekapt op de limieten. */
function cleanItems(items: string[], maxItems: number, maxLength: number) {
  const seen = new Set<string>()
  const result: string[] = []
  for (const raw of items) {
    const item = clip(raw, maxLength)
    const key = item.toLowerCase()
    if (!item || seen.has(key)) continue
    seen.add(key)
    result.push(item)
  }
  return result.slice(0, maxItems)
}

/** Alle ingevulde regels (zonder afkappen), om te kunnen melden dat er te veel zijn. */
export function filledLines(value: string, splitOnComma = false) {
  return value
    .split(splitOnComma ? /[\n,]/ : "\n")
    .map((line) => line.trim())
    .filter(Boolean)
}

/** Eén item per regel, opgeschoond en afgekapt. */
export function splitLines(value: string, maxItems: number = LIMITS.listItems, maxLength: number = LIMITS.listItem) {
  return cleanItems(filledLines(value), maxItems, maxLength)
}

/** Vermijdwoorden: per regel of gescheiden door komma's. */
export function splitWords(value: string) {
  return cleanItems(filledLines(value, true), LIMITS.avoidWords, LIMITS.avoidWord)
}

/** Diensten zonder naam vallen weg; naam en prijs afgekapt op de limiet. */
export function cleanServices(rows: ServiceRow[]): CustomerService[] {
  return rows
    .map((row) => ({ name: clip(row.name, LIMITS.serviceField), price: clip(row.price, LIMITS.serviceField) }))
    .filter((service) => service.name)
    .slice(0, LIMITS.services)
}

export function toProfile(form: ProfielForm): CustomerProfile {
  return {
    company_type: clip(form.companyType, LIMITS.text),
    service_area: clip(form.serviceArea, LIMITS.text),
    target_audience: clip(form.targetAudience, LIMITS.text),
    specialties: clip(form.specialties, LIMITS.text),
    services: cleanServices(form.services),
    services_source: clip(form.servicesSource, LIMITS.text),
    usps: splitLines(form.usps),
    reviews: clip(form.reviews, LIMITS.text),
    certifications: clip(form.certifications, LIMITS.text),
    team: clip(form.team, LIMITS.text),
    cases: splitLines(form.cases),
    language_level: clip(form.languageLevel, LIMITS.text),
    fixed_cta: clip(form.fixedCta, LIMITS.text),
    example_urls: splitLines(form.exampleUrls, LIMITS.exampleUrls, LIMITS.exampleUrl),
    avoid_words: splitWords(form.avoidWords),
    content_rules: splitLines(form.contentRules),
  }
}

// --- Formulier → PATCH-body -------------------------------------------------------------------

export type CustomerPatchBody = {
  name: string
  base_url: string
  seo_customer_since: string | null
  seo_goals: string | null
  tone_of_voice: string | null
  form_of_address: "je" | "u" | null
  category_id: string | null
  target_blogs_per_month: number | null
  target_links_per_month: number | null
  spreadsheet_url: string | null
  profile: CustomerProfile
}

function parseCount(value: string) {
  const trimmed = value.trim()
  return trimmed === "" ? null : Number(trimmed)
}

function isValidCount(value: number | null) {
  return value === null || (Number.isInteger(value) && value >= 0)
}

/** Foutmelding voor ongeldige invoer; null als alles klopt. Naam en website controleert de backend. */
export function validate(form: ProfielForm): string | null {
  if (!isValidCount(parseCount(form.targetBlogsPerMonth))) {
    return "Aantal blogs per maand moet een positief getal zijn."
  }
  if (!isValidCount(parseCount(form.targetLinksPerMonth))) {
    return "Aantal links per maand moet een positief getal zijn."
  }
  return null
}

export function toPayload(form: ProfielForm): CustomerPatchBody {
  return {
    name: form.name.trim(),
    base_url: form.baseUrl.trim(),
    seo_customer_since: form.seoCustomerSince.trim() || null,
    seo_goals: form.seoGoals.trim() || null,
    tone_of_voice: form.toneOfVoice.trim() || null,
    form_of_address: form.formOfAddress || null,
    category_id: form.categoryId || null,
    target_blogs_per_month: parseCount(form.targetBlogsPerMonth),
    target_links_per_month: parseCount(form.targetLinksPerMonth),
    spreadsheet_url: form.spreadsheetUrl.trim() || null,
    profile: toProfile(form),
  }
}

/**
 * Vergelijkbare vorm van het formulier: gelijk = niets gewijzigd. De aantallen gaan als tekst
 * mee, zodat ook ongeldige invoer als wijziging telt.
 */
export function formKey(form: ProfielForm) {
  return JSON.stringify({
    ...toPayload(form),
    target_blogs_per_month: form.targetBlogsPerMonth.trim(),
    target_links_per_month: form.targetLinksPerMonth.trim(),
  })
}
