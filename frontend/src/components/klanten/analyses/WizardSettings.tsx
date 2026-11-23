"use client"

import { checkboxClass, selectClass, Switch } from "@/components/klanten/analyses/form-controls"
import {
  ALL_MODULES,
  COUNTRY_LABELS,
  countryLabel,
  MODULES,
  TOP_N_OPTIONS,
  type Module,
  type Sources,
  type TopN,
} from "@/lib/competitor-analysis"
import { cn } from "@/lib/utils"

const card = "flex flex-col gap-4 rounded-xl border bg-card px-6 py-5"
const fieldLabel = "mb-1 block text-sm font-medium"

/** Kaart "Instellingen": land, (uitgeschakeld) locatie en apparaat, top X en uitsluiten. */
export function WizardSettingsCard({
  country,
  onCountryChange,
  defaultCountry,
  topN,
  onTopNChange,
  excludeAggregators,
  onExcludeAggregatorsChange,
}: {
  country: string
  onCountryChange: (country: string) => void
  /** Uit het voorstel; staat in de lijst, ook als hij niet in `COUNTRY_LABELS` staat. */
  defaultCountry: string
  topN: TopN
  onTopNChange: (topN: TopN) => void
  excludeAggregators: boolean
  onExcludeAggregatorsChange: (value: boolean) => void
}) {
  const countries = Object.keys(COUNTRY_LABELS)
  for (const code of [defaultCountry, country]) {
    if (code && !countries.includes(code)) countries.push(code)
  }

  return (
    <section aria-labelledby="wizard-settings-title" className={card}>
      <h2 id="wizard-settings-title" className="text-base font-semibold">
        Instellingen
      </h2>

      <div>
        <label htmlFor="wizard-country" className={fieldLabel}>
          Land / taal
        </label>
        <select
          id="wizard-country"
          className={selectClass}
          value={country}
          onChange={(event) => onCountryChange(event.target.value)}
        >
          {countries.map((code) => (
            <option key={code} value={code}>
              {countryLabel(code)}
            </option>
          ))}
        </select>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label htmlFor="wizard-location" className={fieldLabel}>
            Locatie
          </label>
          <select id="wizard-location" className={selectClass} disabled aria-describedby="wizard-location-hint">
            <option>Heel {countryLabel(country)}</option>
          </select>
        </div>
        <div>
          <label htmlFor="wizard-device" className={fieldLabel}>
            Apparaat
          </label>
          <select id="wizard-device" className={selectClass} disabled aria-describedby="wizard-location-hint">
            <option>Standaard</option>
          </select>
        </div>
        <p id="wizard-location-hint" className="col-span-2 -mt-1 text-xs text-muted-foreground">
          Ahrefs kent alleen een land; locatie en apparaat zijn niet in te stellen.
        </p>
      </div>

      <fieldset>
        <legend className={fieldLabel}>Aantal concurrenten (top X)</legend>
        <div className="grid grid-cols-4 overflow-hidden rounded-md border shadow-xs">
          {TOP_N_OPTIONS.map((option, index) => (
            <label key={option} className={cn("relative", index > 0 && "border-l")}>
              <input
                type="radio"
                name="wizard-top-n"
                value={option}
                checked={topN === option}
                onChange={() => onTopNChange(option)}
                className="peer sr-only"
              />
              <span className="flex h-9 cursor-pointer items-center justify-center text-sm font-medium transition-colors peer-checked:bg-primary peer-checked:text-primary-foreground peer-focus-visible:ring-[3px] peer-focus-visible:ring-ring/50 peer-focus-visible:ring-inset hover:bg-muted peer-checked:hover:bg-primary">
                <span className="sr-only">Top </span>
                {option}
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      <div className="space-y-1">
        <Switch
          checked={excludeAggregators}
          onCheckedChange={onExcludeAggregatorsChange}
          label="Vergelijkingssites & gidsen uitsluiten"
        />
        <p className="pl-11 text-xs text-muted-foreground">
          Bureauvergelijkers, Wikipedia en bedrijvengidsen tellen niet mee in de mediaan
        </p>
      </div>
    </section>
  )
}

/** Toelichting bij een module als de bron erachter ontbreekt. */
function moduleNote(module: Module, sources: Sources): string | null {
  const claude = sources.claude.state === "ok"
  if ((module === "topics" || module === "eeat") && !claude) return "Claude is niet ingesteld: blijft leeg."
  if (module === "tech" && sources.pagespeed.state !== "ok") return "PageSpeed is niet ingesteld: alleen schema.org."
  return null
}

/** Kaart "Wat analyseren?": de zes modules; minstens één aan. */
export function WizardModulesCard({
  modules,
  onModulesChange,
  sources,
  error,
}: {
  modules: Module[]
  onModulesChange: (modules: Module[]) => void
  sources: Sources
  error: string | null
}) {
  function toggle(module: Module, checked: boolean) {
    const next = new Set(modules)
    if (checked) next.add(module)
    else next.delete(module)
    onModulesChange(ALL_MODULES.filter((item) => next.has(item)))
  }

  return (
    <section className={card}>
      <fieldset aria-describedby={error ? "wizard-modules-error" : undefined}>
        <legend className="mb-3 text-base font-semibold">Wat analyseren?</legend>
        <ul className="space-y-3">
          {ALL_MODULES.map((module) => {
            const note = moduleNote(module, sources)
            const id = `wizard-module-${module}`
            return (
              <li key={module}>
                <label htmlFor={id} className="flex cursor-pointer items-start gap-3">
                  <input
                    id={id}
                    type="checkbox"
                    className={cn(checkboxClass, "mt-0.5")}
                    checked={modules.includes(module)}
                    onChange={(event) => toggle(module, event.target.checked)}
                    aria-describedby={`${id}-description`}
                  />
                  <span className="min-w-0 space-y-0.5">
                    <span className="block text-sm font-medium">{MODULES[module].label}</span>
                    <span id={`${id}-description`} className="block text-xs text-muted-foreground">
                      {MODULES[module].description}
                      {note && <span className="block text-amber-700 dark:text-amber-400">{note}</span>}
                    </span>
                  </span>
                </label>
              </li>
            )
          })}
        </ul>
      </fieldset>
      {error && (
        <p id="wizard-modules-error" role="alert" className="text-sm text-red-700 dark:text-red-300">
          {error}
        </p>
      )}
    </section>
  )
}
