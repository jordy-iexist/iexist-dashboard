"use client"

// Kaart "Traject & afspraken" (de velden van het oude formulier "Klant bewerken" die niet in het
// profielontwerp staan) en de gevarenzone met "Klant verwijderen".

import { Loader2 } from "lucide-react"
import { useId } from "react"

import { CategorySelect } from "@/components/klanten/CategorySelect"
import { formatShortDate, ResultCard, shortUrl } from "@/components/klanten/analyses/result-parts"
import { Button } from "@/components/ui/button"

import { type CardProps } from "./profiel-form"
import { Fields, ProfielCard, Row, Rows, TextAreaField, TextField } from "./profiel-parts"

const SPREADSHEET_HELP =
  "De interne spreadsheet is altijd bereikbaar via de Spreadsheet-knop in de klantenlijst."

export function TrajectCard({
  form,
  update,
  editing,
  onToggle,
  disabled,
  categoryName,
}: CardProps & {
  /** Naam van de gekozen categorie; null = geen categorie. */
  categoryName: string | null
}) {
  const categoryLabelId = useId()
  const spreadsheetUrl = form.spreadsheetUrl.trim()
  const empty =
    !form.seoCustomerSince &&
    !form.categoryId &&
    !form.targetBlogsPerMonth.trim() &&
    !form.targetLinksPerMonth.trim() &&
    !spreadsheetUrl &&
    !form.seoGoals.trim()

  return (
    <ProfielCard
      id="traject"
      title="Traject & afspraken"
      description="Afspraken met de klant; worden niet aan Claude meegegeven."
      editing={editing}
      onToggle={onToggle}
      empty={empty}
      emptyText="Nog geen trajectgegevens of afspraken vastgelegd."
    >
      {editing ? (
        <div className="grid gap-x-8 gap-y-3 lg:grid-cols-2">
          <Fields>
            <TextField
              label="Traject gestart"
              type="date"
              value={form.seoCustomerSince}
              onChange={(v) => update("seoCustomerSince", v)}
              disabled={disabled}
            />
            <div className="flex flex-col gap-1 sm:flex-row sm:gap-4">
              <span
                id={categoryLabelId}
                className="pt-2 text-[13px] text-muted-foreground sm:w-[170px] sm:shrink-0"
              >
                Branche / categorie
              </span>
              <div role="group" aria-labelledby={categoryLabelId} className="min-w-0 flex-1">
                <CategorySelect
                  value={form.categoryId}
                  onChange={(v) => update("categoryId", v)}
                  disabled={disabled}
                />
              </div>
            </div>
            <TextField
              label="Blogs per maand (doel)"
              type="number"
              value={form.targetBlogsPerMonth}
              onChange={(v) => update("targetBlogsPerMonth", v)}
              placeholder="Bijv. 4"
              disabled={disabled}
            />
            <TextField
              label="Links per maand (doel)"
              type="number"
              value={form.targetLinksPerMonth}
              onChange={(v) => update("targetLinksPerMonth", v)}
              placeholder="Bijv. 2"
              disabled={disabled}
            />
            <TextField
              label="Externe spreadsheet"
              type="url"
              value={form.spreadsheetUrl}
              onChange={(v) => update("spreadsheetUrl", v)}
              placeholder="https://docs.google.com/..."
              help={`Optioneel. ${SPREADSHEET_HELP}`}
              disabled={disabled}
            />
          </Fields>
          <TextAreaField
            label="Afspraken / SEO-doelstellingen"
            value={form.seoGoals}
            onChange={(v) => update("seoGoals", v)}
            placeholder="Beschrijf de afspraken en SEO-doelstellingen voor deze klant"
            disabled={disabled}
            rows={8}
          />
        </div>
      ) : (
        <div className="grid gap-x-8 lg:grid-cols-2">
          <Rows>
            <Row label="Traject gestart">{formatShortDate(form.seoCustomerSince)}</Row>
            <Row label="Branche / categorie">{categoryName}</Row>
            <Row label="Blogs per maand (doel)">{form.targetBlogsPerMonth.trim() || null}</Row>
            <Row label="Links per maand (doel)">{form.targetLinksPerMonth.trim() || null}</Row>
            <Row label="Externe spreadsheet">
              {spreadsheetUrl ? (
                <a
                  href={spreadsheetUrl}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="break-all underline-offset-4 hover:underline"
                >
                  {shortUrl(spreadsheetUrl)}
                </a>
              ) : null}
            </Row>
          </Rows>
          <Rows>
            <Row label="Afspraken / SEO-doelstellingen">{form.seoGoals.trim() || null}</Row>
          </Rows>
        </div>
      )}
    </ProfielCard>
  )
}

/** Gevarenzone: klant definitief verwijderen. */
export function KlantVerwijderen({
  onDelete,
  deleting,
  disabled,
}: {
  onDelete: () => void
  deleting: boolean
  disabled: boolean
}) {
  return (
    <ResultCard
      id="profiel-verwijderen"
      title={<span className="text-destructive">Gevarenzone</span>}
      description={
        <>
          Verwijdert deze klant, inclusief keywords, SERP-scans en meta runs, definitief. Blogs en
          landingspagina&apos;s blijven bestaan maar verliezen hun klantkoppeling.
        </>
      }
      className="border-destructive/40"
    >
      <div>
        <Button type="button" variant="destructive" onClick={onDelete} disabled={disabled}>
          {deleting && <Loader2 className="animate-spin" aria-hidden="true" />}
          Klant verwijderen
        </Button>
      </div>
    </ResultCard>
  )
}
