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

// --- Voorstel uit de website ------------------------------------------------------------------

/** Wat het aanvullen heeft toegevoegd, voor de melding. */
export type SuggestionCounts = {
  /** Nieuwe dienstrijen. */
  services: number
  /** Prijzen uit de website: bij nieuwe diensten en bij bestaande diensten zonder prijs. */
  prices: number
  usps: number
  cases: number
  /** Gevulde tekstvelden (Bedrijf en Bewijs). */
  fields: number
}

export type MergeResult = {
  form: ProfielForm
  /** Kaarten waarin iets is aangevuld. */
  changedCards: CardId[]
  counts: SuggestionCounts
}

/** Tekstvelden die alleen gevuld worden als ze leeg zijn, met de kaart waarop ze staan. */
const SUGGESTED_TEXT_FIELDS = [
  ["companyType", "company_type", "bedrijf"],
  ["serviceArea", "service_area", "bedrijf"],
  ["targetAudience", "target_audience", "bedrijf"],
  ["specialties", "specialties", "bedrijf"],
  ["reviews", "reviews", "bewijs"],
  ["certifications", "certifications", "bewijs"],
  ["team", "team", "bewijs"],
] as const

/** Vergelijkbare naam van een dienst: getrimd, witruimte samengevoegd, kleine letters. */
function serviceNameKey(name: string) {
  return name.trim().replace(/\s+/g, " ").toLowerCase()
}

/**
 * Nieuwe regels onder een lijst (één item per regel). De bestaande tekst blijft letterlijk
 * staan; dubbelen (hoofdletterongevoelig) en items boven de limiet vallen weg.
 */
function appendLines(value: string, suggested: string[]) {
  const existing = splitLines(value)
  const seen = new Set(existing.map((item) => item.toLowerCase()))
  const added: string[] = []
  for (const raw of suggested) {
    if (existing.length + added.length >= LIMITS.listItems) break
    const item = clip(raw.replace(/\s+/g, " "), LIMITS.listItem)
    const key = item.toLowerCase()
    if (!item || seen.has(key)) continue
    seen.add(key)
    added.push(item)
  }
  if (added.length === 0) return { value, added: 0 }
  const separator = value === "" || value.endsWith("\n") ? "" : "\n"
  return { value: `${value}${separator}${added.join("\n")}`, added: added.length }
}

/**
 * Voegt een voorstel uit de website samen met het formulier, volgens "alleen aanvullen": lege
 * velden worden gevuld, bij diensten, USP's en cases komen alleen nieuwe regels erbij, en een
 * bestaande dienst zonder prijs krijgt de prijs van de website. Wat al is ingevuld blijft staan.
 * Zuiver: `today` (dd-mm-jjjj) komt van buiten. Verandert er niets, dan is `form` hetzelfde object.
 */
export function mergeSuggestion(form: ProfielForm, suggestion: unknown, today: string): MergeResult {
  const profile = parseProfile(suggestion)
  const counts: SuggestionCounts = { services: 0, prices: 0, usps: 0, cases: 0, fields: 0 }
  const changed = new Set<CardId>()
  const next: ProfielForm = { ...form }

  // Tekstvelden: alleen als het veld leeg is.
  for (const [field, source, card] of SUGGESTED_TEXT_FIELDS) {
    const value = clip(profile[source], LIMITS.text)
    if (!value || form[field].trim() !== "") continue
    next[field] = value
    counts.fields += 1
    changed.add(card)
  }

  // Diensten: nieuwe namen achteraan, prijs alleen bij een bestaande dienst zonder prijs.
  // Rijen zonder naam blijven onaangeroerd; de limiet telt alleen diensten met een naam.
  const rows = [...form.services]
  const indexByName = new Map<string, number>()
  rows.forEach((row, index) => {
    const key = serviceNameKey(row.name)
    if (key && !indexByName.has(key)) indexByName.set(key, index)
  })
  let namedServices = cleanServices(form.services).length
  let servicesChanged = false
  for (const service of profile.services) {
    const name = clip(service.name.replace(/\s+/g, " "), LIMITS.serviceField)
    const price = clip(service.price, LIMITS.serviceField)
    const key = serviceNameKey(name)
    if (!key) continue

    const index = indexByName.get(key)
    if (index !== undefined) {
      if (price && rows[index].price.trim() === "") {
        rows[index] = { ...rows[index], price }
        counts.prices += 1
        servicesChanged = true
      }
      continue
    }

    if (namedServices >= LIMITS.services) continue
    indexByName.set(key, rows.length)
    rows.push(newServiceRow({ name, price }))
    namedServices += 1
    counts.services += 1
    if (price) counts.prices += 1
    servicesChanged = true
  }
  if (servicesChanged) {
    next.services = rows
    if (form.servicesSource.trim() === "") next.servicesSource = `website, ${today}`
    changed.add("diensten")
  }

  // USP's en cases: nieuwe items onderaan.
  const usps = appendLines(form.usps, profile.usps)
  if (usps.added > 0) {
    next.usps = usps.value
    counts.usps = usps.added
    changed.add("usps")
  }
  const cases = appendLines(form.cases, profile.cases)
  if (cases.added > 0) {
    next.cases = cases.value
    counts.cases = cases.added
    changed.add("bewijs")
  }

  const order: CardId[] = ["bedrijf", "diensten", "usps", "bewijs"]
  return {
    form: changed.size > 0 ? next : form,
    changedCards: order.filter((card) => changed.has(card)),
    counts,
  }
}

function plural(count: number, one: string, many: string) {
  return `${count} ${count === 1 ? one : many}`
}

/** "a", "a en b", "a, b en c". */
function joinParts(parts: string[]) {
  if (parts.length <= 1) return parts.join("")
  return `${parts.slice(0, -1).join(", ")} en ${parts[parts.length - 1]}`
}

/**
 * Melding na het aanvullen. `saveLabel` is de tekst van de opslaanknop ("Opslaan" of
 * "Klant toevoegen"); `note` uit het antwoord komt erachter.
 */
export function suggestionMessage(
  counts: SuggestionCounts,
  pagesRead: number,
  note: string | null,
  saveLabel: string
) {
  const pagesText = plural(pagesRead, "pagina", "pagina's")
  const parts = [
    counts.services > 0 && plural(counts.services, "dienst", "diensten"),
    counts.prices > 0 && plural(counts.prices, "prijs", "prijzen"),
    counts.usps > 0 && plural(counts.usps, "USP", "USP's"),
    counts.cases > 0 && plural(counts.cases, "case", "cases"),
    counts.fields > 0 && plural(counts.fields, "veld", "velden"),
  ].filter((part): part is string => !!part)

  const sentences: string[] = []
  if (parts.length === 0) {
    sentences.push(
      pagesRead > 0
        ? `Niets nieuws gevonden op de website (${pagesText} gelezen).`
        : "Niets nieuws gevonden op de website."
    )
  } else {
    const source = pagesRead > 0 ? `vanaf ${pagesText}` : "vanaf de website"
    sentences.push(`Aangevuld ${source}: ${joinParts(parts)}.`)
    sentences.push(`Loop de geopende kaarten na en klik op ${saveLabel}.`)
    if (counts.cases > 0) sentences.push("Controleer bij cases of de klant toestemming heeft gegeven.")
  }
  const extra = note?.trim()
  if (extra) sentences.push(extra)
  return sentences.join(" ")
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
