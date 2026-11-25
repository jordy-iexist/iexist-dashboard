"use client"

// Rechterkolom van het klantprofiel: Tone of voice en Regels voor AI-content.

import { useId } from "react"

import { shortUrl } from "@/components/klanten/analyses/result-parts"
import { fieldClassName } from "@/components/settings/SettingsSection"
import { cn } from "@/lib/utils"

import {
  LIMITS,
  splitLines,
  splitWords,
  type CardProps,
  type FormOfAddress,
} from "./profiel-form"
import {
  FieldRow,
  Fields,
  ItemList,
  PillList,
  ProfielCard,
  Row,
  Rows,
  SubHeading,
  TextAreaField,
  TextField,
} from "./profiel-parts"

const FORM_OF_ADDRESS_LABELS: Record<Exclude<FormOfAddress, "">, string> = {
  je: "je / jij",
  u: "u",
}

function isHttpUrl(value: string) {
  return /^https?:\/\//i.test(value)
}

// --- Tone of voice ----------------------------------------------------------------------------

export function ToneCard({ form, update, editing, onToggle, disabled }: CardProps) {
  const exampleUrls = splitLines(form.exampleUrls, LIMITS.exampleUrls, LIMITS.exampleUrl)
  const avoidWords = splitWords(form.avoidWords)
  const examplesId = useId()
  const avoidId = useId()
  const empty =
    !form.toneOfVoice.trim() &&
    !form.formOfAddress &&
    !form.languageLevel.trim() &&
    !form.fixedCta.trim() &&
    exampleUrls.length === 0 &&
    avoidWords.length === 0

  return (
    <ProfielCard
      id="tone"
      title="Tone of voice"
      description="Afgeleid uit bestaande teksten – handmatig bijgesteld."
      editing={editing}
      onToggle={onToggle}
      empty={empty}
      emptyText="Nog geen tone of voice. Leg vast hoe teksten voor deze klant moeten klinken."
    >
      {editing ? (
        <Fields>
          <FieldRow label="Aanspreekvorm">
            {({ id }) => (
              <select
                id={id}
                className={cn(fieldClassName, "h-9 bg-background py-0")}
                value={form.formOfAddress}
                onChange={(event) => update("formOfAddress", event.target.value as FormOfAddress)}
                disabled={disabled}
              >
                <option value="">Niet vastgelegd</option>
                <option value="je">Je-vorm</option>
                <option value="u">U-vorm</option>
              </select>
            )}
          </FieldRow>
          <TextAreaField
            label="Toon"
            value={form.toneOfVoice}
            onChange={(v) => update("toneOfVoice", v)}
            placeholder="Bijv. nuchter, deskundig, zonder jargon"
            help="De content brief en de concepttekst volgen dit letterlijk."
            disabled={disabled}
            rows={3}
          />
          <TextField
            label="Taalniveau"
            value={form.languageLevel}
            onChange={(v) => update("languageLevel", v)}
            maxLength={LIMITS.text}
            placeholder="Bijv. B1, eenvoudig Nederlands"
            disabled={disabled}
          />
          <TextField
            label="Vaste CTA"
            value={form.fixedCta}
            onChange={(v) => update("fixedCta", v)}
            maxLength={LIMITS.text}
            placeholder="Bijv. Plan een gratis adviesgesprek"
            disabled={disabled}
          />
          <TextAreaField
            label="Voorbeeldteksten"
            value={form.exampleUrls}
            onChange={(v) => update("exampleUrls", v)}
            placeholder="https://www.voorbeeld.nl/over-ons"
            help={`Eén URL per regel, maximaal ${LIMITS.exampleUrls}. Alleen ter referentie: Claude haalt deze pagina's niet op.`}
            maxItems={LIMITS.exampleUrls}
            maxItemLength={LIMITS.exampleUrl}
            disabled={disabled}
            rows={3}
          />
          <TextAreaField
            label="Woorden die we vermijden"
            value={form.avoidWords}
            onChange={(v) => update("avoidWords", v)}
            placeholder="Bijv. goedkoop, ontzorgen, uniek"
            help={`Per regel of gescheiden door komma's, maximaal ${LIMITS.avoidWords} woorden van ${LIMITS.avoidWord} tekens.`}
            maxItems={LIMITS.avoidWords}
            maxItemLength={LIMITS.avoidWord}
            splitOnComma
            disabled={disabled}
            rows={3}
          />
        </Fields>
      ) : (
        <>
          <Rows>
            <Row label="Aanspreekvorm">
              {form.formOfAddress ? FORM_OF_ADDRESS_LABELS[form.formOfAddress] : null}
            </Row>
            <Row label="Toon">{form.toneOfVoice.trim() || null}</Row>
            <Row label="Taalniveau">{form.languageLevel.trim() || null}</Row>
            <Row label="Vaste CTA">{form.fixedCta.trim() || null}</Row>
          </Rows>
          <div className="space-y-2">
            <SubHeading id={examplesId}>Voorbeeldteksten</SubHeading>
            {exampleUrls.length > 0 ? (
              <PillList
                tone="blue"
                labelledBy={examplesId}
                items={exampleUrls.map((url) => ({
                  label: shortUrl(url),
                  href: isHttpUrl(url) ? url : undefined,
                  title: url,
                }))}
              />
            ) : (
              <p className="text-[13px] text-muted-foreground">Niet ingevuld</p>
            )}
          </div>
          <div className="space-y-2">
            <SubHeading id={avoidId}>Woorden die we vermijden</SubHeading>
            {avoidWords.length > 0 ? (
              <PillList
                tone="red"
                labelledBy={avoidId}
                items={avoidWords.map((word) => ({ label: word }))}
              />
            ) : (
              <p className="text-[13px] text-muted-foreground">Niet ingevuld</p>
            )}
          </div>
        </>
      )}
    </ProfielCard>
  )
}

// --- Regels voor AI-content -------------------------------------------------------------------

export function RegelsCard({ form, update, editing, onToggle, disabled }: CardProps) {
  const rules = splitLines(form.contentRules)
  return (
    <ProfielCard
      id="regels"
      title="Regels voor AI-content"
      description="Harde regels – Claude controleert elke tekst hierop."
      editing={editing}
      onToggle={onToggle}
      empty={rules.length === 0}
      emptyText="Nog geen regels. Bijv. wat Claude nooit mag beloven of altijd moet vermelden."
    >
      {editing ? (
        <TextAreaField
          label="Regels"
          value={form.contentRules}
          onChange={(v) => update("contentRules", v)}
          placeholder={"Bijv. Noem nooit garanties op posities in Google\nVerwijs altijd naar het contactformulier"}
          help={`Eén per regel, maximaal ${LIMITS.listItems}.`}
          maxItems={LIMITS.listItems}
          maxItemLength={LIMITS.listItem}
          disabled={disabled}
          rows={6}
        />
      ) : (
        <ItemList items={rules} icon="alert" />
      )}
    </ProfielCard>
  )
}
