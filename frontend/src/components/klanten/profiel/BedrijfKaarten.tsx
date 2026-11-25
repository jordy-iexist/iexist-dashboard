"use client"

// Linkerkolom van het klantprofiel: Bedrijf, Diensten & prijzen, USP's en Bewijs & E-E-A-T.

import { useId } from "react"
import { Plus, Trash2 } from "lucide-react"

import { shortUrl } from "@/components/klanten/analyses/result-parts"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

import {
  cleanServices,
  LIMITS,
  newServiceRow,
  splitLines,
  type CardProps,
  type ServiceRow,
} from "./profiel-form"
import {
  Fields,
  ItemList,
  ProfielCard,
  Row,
  Rows,
  SubHeading,
  TextAreaField,
  TextField,
} from "./profiel-parts"

const LIST_HELP = `Eén per regel, maximaal ${LIMITS.listItems}.`

// --- Bedrijf ----------------------------------------------------------------------------------

export function BedrijfCard({ form, update, editing, onToggle, disabled }: CardProps) {
  return (
    <ProfielCard id="bedrijf" title="Bedrijf" editing={editing} onToggle={onToggle}>
      {editing ? (
        <Fields>
          <TextField
            label="Naam"
            value={form.name}
            onChange={(v) => update("name", v)}
            placeholder="Bijv. Klant A"
            disabled={disabled}
            required
          />
          <TextField
            label="Website"
            type="url"
            required
            value={form.baseUrl}
            onChange={(v) => update("baseUrl", v)}
            placeholder="https://www.voorbeeld.nl"
            disabled={disabled}
          />
          <TextField
            label="Type"
            value={form.companyType}
            onChange={(v) => update("companyType", v)}
            maxLength={LIMITS.text}
            placeholder="Bijv. installatiebedrijf, webshop, adviesbureau"
            disabled={disabled}
          />
          <TextField
            label="Werkgebied"
            value={form.serviceArea}
            onChange={(v) => update("serviceArea", v)}
            maxLength={LIMITS.text}
            placeholder="Bijv. Utrecht en omstreken"
            disabled={disabled}
          />
          <TextField
            label="Doelgroep"
            value={form.targetAudience}
            onChange={(v) => update("targetAudience", v)}
            maxLength={LIMITS.text}
            placeholder="Bijv. mkb-ondernemers met 10–50 medewerkers"
            disabled={disabled}
          />
          <TextField
            label="Specialisaties"
            value={form.specialties}
            onChange={(v) => update("specialties", v)}
            maxLength={LIMITS.text}
            disabled={disabled}
          />
          <p className="text-xs text-muted-foreground">
            <span aria-hidden="true" className="text-destructive">*</span> Naam en website zijn verplicht.
          </p>
        </Fields>
      ) : (
        <Rows>
          <Row label="Naam">{form.name.trim() || null}</Row>
          <Row label="Website">
            {form.baseUrl.trim() ? (
              <a
                href={form.baseUrl.trim()}
                target="_blank"
                rel="noreferrer noopener"
                className="break-all underline-offset-4 hover:underline"
              >
                {shortUrl(form.baseUrl.trim())}
              </a>
            ) : null}
          </Row>
          <Row label="Type">{form.companyType.trim() || null}</Row>
          <Row label="Werkgebied">{form.serviceArea.trim() || null}</Row>
          <Row label="Doelgroep">{form.targetAudience.trim() || null}</Row>
          <Row label="Specialisaties">{form.specialties.trim() || null}</Row>
        </Rows>
      )}
    </ProfielCard>
  )
}

// --- Diensten & prijzen -----------------------------------------------------------------------

function ServiceRowFields({
  row,
  index,
  onChange,
  onRemove,
  disabled,
}: {
  row: ServiceRow
  index: number
  onChange: (row: ServiceRow) => void
  onRemove: () => void
  disabled: boolean
}) {
  const id = useId()
  return (
    <li className="flex items-center gap-2">
      <label htmlFor={`${id}-naam`} className="sr-only">
        Dienst {index + 1}
      </label>
      <Input
        id={`${id}-naam`}
        value={row.name}
        maxLength={LIMITS.serviceField}
        placeholder="Dienst"
        disabled={disabled}
        onChange={(event) => onChange({ ...row, name: event.target.value })}
      />
      <label htmlFor={`${id}-prijs`} className="sr-only">
        Prijs van dienst {index + 1}
      </label>
      <Input
        id={`${id}-prijs`}
        value={row.price}
        maxLength={LIMITS.serviceField}
        placeholder="Prijs, bijv. vanaf € 750 per maand"
        disabled={disabled}
        onChange={(event) => onChange({ ...row, price: event.target.value })}
      />
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="shrink-0 text-muted-foreground"
        onClick={onRemove}
        disabled={disabled}
        title="Dienst verwijderen"
      >
        <Trash2 aria-hidden="true" />
        <span className="sr-only">Dienst {index + 1} verwijderen</span>
      </Button>
    </li>
  )
}

export function DienstenCard({ form, update, editing, onToggle, disabled }: CardProps) {
  const services = cleanServices(form.services)
  const source = form.servicesSource.trim()
  const atLimit = form.services.length >= LIMITS.services

  const setRow = (index: number, row: ServiceRow) =>
    update(
      "services",
      form.services.map((current, i) => (i === index ? row : current))
    )

  return (
    <ProfielCard
      id="diensten"
      title="Diensten & prijzen"
      description={`${source ? `Bron: ${source}. ` : ""}Claude gebruikt alleen deze bedragen.`}
      editing={editing}
      onToggle={onToggle}
      empty={services.length === 0 && !source}
      emptyText="Nog geen diensten of prijzen. Zonder bedragen noemt Claude geen prijzen."
    >
      {editing ? (
        <div className="flex flex-col gap-3">
          {form.services.length > 0 && (
            <ul className="flex flex-col gap-2">
              {form.services.map((row, index) => (
                <ServiceRowFields
                  key={row.key}
                  row={row}
                  index={index}
                  disabled={disabled}
                  onChange={(next) => setRow(index, next)}
                  onRemove={() =>
                    update(
                      "services",
                      form.services.filter((_, i) => i !== index)
                    )
                  }
                />
              ))}
            </ul>
          )}
          <div className="flex flex-wrap items-center gap-3">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={disabled || atLimit}
              onClick={() => update("services", [...form.services, newServiceRow()])}
            >
              <Plus aria-hidden="true" />
              Dienst toevoegen
            </Button>
            <span className="text-xs text-muted-foreground">
              {atLimit
                ? `Maximaal ${LIMITS.services} diensten.`
                : "Rijen zonder dienst worden niet bewaard."}
            </span>
          </div>
          <TextField
            label="Bron"
            value={form.servicesSource}
            onChange={(v) => update("servicesSource", v)}
            maxLength={LIMITS.text}
            placeholder="Bijv. prijslijst 2026"
            disabled={disabled}
          />
        </div>
      ) : services.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">Nog geen diensten ingevuld.</p>
      ) : (
        <Rows>
          {services.map((service, index) => (
            <Row key={`${index}-${service.name}`} label={service.name}>
              {service.price || null}
            </Row>
          ))}
        </Rows>
      )}
    </ProfielCard>
  )
}

// --- USP's ------------------------------------------------------------------------------------

export function UspsCard({ form, update, editing, onToggle, disabled }: CardProps) {
  const usps = splitLines(form.usps)
  return (
    <ProfielCard
      id="usps"
      title="USP's"
      editing={editing}
      onToggle={onToggle}
      empty={usps.length === 0}
      emptyText="Nog geen USP's. Waarom kiezen klanten voor dit bedrijf?"
    >
      {editing ? (
        <TextAreaField
          label="USP's"
          value={form.usps}
          onChange={(v) => update("usps", v)}
          placeholder={"Bijv. Persoonlijk contact met een vaste specialist\nBinnen 24 uur een offerte"}
          help={LIST_HELP}
          maxItems={LIMITS.listItems}
          maxItemLength={LIMITS.listItem}
          disabled={disabled}
          rows={6}
        />
      ) : (
        <ItemList items={usps} icon="check" />
      )}
    </ProfielCard>
  )
}

// --- Bewijs & E-E-A-T -------------------------------------------------------------------------

export function BewijsCard({ form, update, editing, onToggle, disabled }: CardProps) {
  const cases = splitLines(form.cases)
  const casesId = useId()
  const empty =
    !form.reviews.trim() && !form.certifications.trim() && !form.team.trim() && cases.length === 0

  return (
    <ProfielCard
      id="bewijs"
      title="Bewijs & E-E-A-T"
      description="Wordt gebruikt voor cases, reviews en auteursinformatie in teksten."
      editing={editing}
      onToggle={onToggle}
      empty={empty}
      emptyText="Nog geen reviews, certificeringen, team of cases. Claude noemt alleen bewijs dat hier staat."
    >
      {editing ? (
        <Fields>
          <TextField
            label="Reviews"
            value={form.reviews}
            onChange={(v) => update("reviews", v)}
            maxLength={LIMITS.text}
            placeholder="Bijv. 4,8 uit 5 op Google (120 reviews)"
            disabled={disabled}
          />
          <TextField
            label="Certificeringen"
            value={form.certifications}
            onChange={(v) => update("certifications", v)}
            maxLength={LIMITS.text}
            disabled={disabled}
          />
          <TextField
            label="Team (auteurs)"
            value={form.team}
            onChange={(v) => update("team", v)}
            maxLength={LIMITS.text}
            placeholder="Bijv. Anna de Vries, SEO-specialist sinds 2015"
            disabled={disabled}
          />
          <TextAreaField
            label="Cases (met toestemming)"
            value={form.cases}
            onChange={(v) => update("cases", v)}
            help={LIST_HELP}
            maxItems={LIMITS.listItems}
            maxItemLength={LIMITS.listItem}
            disabled={disabled}
          />
        </Fields>
      ) : (
        <>
          <Rows>
            <Row label="Reviews">{form.reviews.trim() || null}</Row>
            <Row label="Certificeringen">{form.certifications.trim() || null}</Row>
            <Row label="Team (auteurs)">{form.team.trim() || null}</Row>
          </Rows>
          <div className="space-y-2">
            <SubHeading id={casesId}>Cases (met toestemming)</SubHeading>
            {cases.length > 0 ? (
              <ItemList items={cases} icon="bullet" labelledBy={casesId} />
            ) : (
              <p className="text-[13px] text-muted-foreground">Niet ingevuld</p>
            )}
          </div>
        </>
      )}
    </ProfielCard>
  )
}
