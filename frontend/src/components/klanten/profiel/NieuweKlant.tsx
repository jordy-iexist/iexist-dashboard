"use client"

// Pagina Klant toevoegen: hetzelfde scherm als het klantprofiel, maar voor een klant die nog
// niet bestaat. Bedrijf staat meteen open; "Klant toevoegen" maakt de klant met het hele
// profiel aan in één POST en gaat daarna naar het profiel van de nieuwe klant.

import { useRouter } from "next/navigation"
import { useMemo, useState } from "react"
import { Loader2 } from "lucide-react"

import { ResultCard } from "@/components/klanten/analyses/result-parts"
import { Button } from "@/components/ui/button"

import { emptyForm, formKey, toPayload, validate } from "./profiel-form"
import {
  AiFillButton,
  FeedbackMessage,
  getErrorMessage,
  ProfielHeader,
  ProfielKaarten,
  useAiFill,
  useBeforeUnloadWarning,
  useProfielForm,
  type ErrorResponse,
  type Feedback,
} from "./ProfielPagina"

const EMPTY_KEY = formKey(emptyForm())

/** Koppelingen bestaan pas als de klant er is; geen aanroepen, alleen een melding. */
function KoppelingenPlaceholder() {
  return (
    <ResultCard id="profiel-koppelingen" title="Koppelingen voor deze klant">
      <p className="rounded-lg border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
        Search Console, Pro Rank Tracker en WordPress zie je hier zodra de klant is toegevoegd.
      </p>
    </ResultCard>
  )
}

export function NieuweKlant() {
  const router = useRouter()
  const { form, setForm, update, openCards, setOpenCards, toggleCard } = useProfielForm(emptyForm, [
    "bedrijf",
  ])
  const [saving, setSaving] = useState(false)
  const [feedback, setFeedback] = useState<Feedback>(null)
  const { filling, fill } = useAiFill({
    form,
    setForm,
    setOpenCards,
    setFeedback,
    saveLabel: "Klant toevoegen",
  })

  const filledIn = useMemo(() => formKey(form) !== EMPTY_KEY, [form])
  const hasWebsite = form.baseUrl.trim().length > 0
  // Tijdens het aanvullen staat alles uit, zodat het formulier niet verandert onderweg.
  const busy = saving || filling
  const canSubmit = form.name.trim().length > 0 && hasWebsite && !busy

  // Niet waarschuwen tijdens het doorsturen naar het nieuwe profiel.
  useBeforeUnloadWarning(filledIn && !saving)

  const create = async () => {
    const invalid = validate(form)
    if (invalid) {
      setFeedback({ type: "error", message: invalid })
      return
    }

    setFeedback(null)
    setSaving(true)
    try {
      const response = await fetch("/api/customers", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(toPayload(form)),
      })
      const payload = (await response.json().catch(() => null)) as
        | ({ id?: unknown } & ErrorResponse)
        | null
      if (!response.ok) {
        throw new Error(getErrorMessage(payload, "Kon klant niet toevoegen."))
      }
      const id = typeof payload?.id === "string" && payload.id ? payload.id : null
      router.push(id ? `/dashboard/klanten/${encodeURIComponent(id)}/profiel` : "/dashboard/klanten")
      router.refresh()
    } catch (error) {
      setFeedback({
        type: "error",
        message: error instanceof Error ? error.message : "Kon klant niet toevoegen.",
      })
      setSaving(false)
    }
  }

  return (
    <div className="space-y-6">
      <ProfielHeader
        crumbs={[{ label: "Klanten", href: "/dashboard/klanten" }, { label: "Nieuwe klant" }]}
        title="Klant toevoegen"
        subtitle="Vul het profiel meteen in; het wordt meegegeven aan Claude bij content briefs en concepteksten"
        actions={
          <>
            <AiFillButton
              onClick={() => void fill()}
              loading={filling}
              disabled={!hasWebsite || busy}
              title={hasWebsite ? undefined : "Vul eerst de website in"}
            />
            <Button
              onClick={() => void create()}
              disabled={!canSubmit}
              title={canSubmit || busy ? undefined : "Vul eerst naam en website in"}
            >
              {saving && <Loader2 className="animate-spin" aria-hidden="true" />}
              {saving ? "Klant toevoegen…" : "Klant toevoegen"}
            </Button>
          </>
        }
      />

      <FeedbackMessage feedback={feedback} />

      <ProfielKaarten
        form={form}
        update={update}
        openCards={openCards}
        toggleCard={toggleCard}
        disabled={busy}
        categoryName={form.categoryId ? "Gekozen – wordt bij toevoegen bewaard" : null}
        connections={<KoppelingenPlaceholder />}
      />
    </div>
  )
}
