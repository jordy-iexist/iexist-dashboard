"use client"

// Pagina Klantprofiel: kop met opslaan, de profielkaarten in twee kolommen, "Traject &
// afspraken" en de gevarenzone. Eén formulierstate voor de hele pagina; "Opslaan" stuurt alles
// in één PATCH. Kaarten staan standaard in leesweergave en gaan per kaart in bewerkstand.

import { useRouter } from "next/navigation"
import { useEffect, useMemo, useState } from "react"
import { Loader2 } from "lucide-react"

import { formatShortDate } from "@/components/klanten/analyses/result-parts"
import { Button } from "@/components/ui/button"
import type { CustomerWebsiteDetail } from "@/lib/customer-types"

import { formKey, parseProfile, toForm, toPayload, validate } from "./profiel-form"
import {
  AiFillButton,
  FeedbackMessage,
  getErrorMessage,
  ProfielHeader,
  ProfielKaarten,
  UnsavedNotice,
  useBeforeUnloadWarning,
  useProfielForm,
  type ErrorResponse,
  type Feedback,
} from "./ProfielPagina"
import { KlantVerwijderen } from "./TrajectKaart"

const SUCCESS_VISIBLE_MS = 4000

export function KlantProfiel({
  customer,
  connections,
}: {
  customer: CustomerWebsiteDetail
  /** Kaart "Koppelingen voor deze klant" (servercomponent, laadt los van de pagina). */
  connections: React.ReactNode
}) {
  const router = useRouter()
  const [saved, setSaved] = useState(customer)
  const { form, setForm, update, openCards, setOpenCards, toggleCard } = useProfielForm(() =>
    toForm(customer)
  )
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [feedback, setFeedback] = useState<Feedback>(null)

  const savedKey = useMemo(() => formKey(toForm(saved)), [saved])
  const dirty = useMemo(() => formKey(form) !== savedKey, [form, savedKey])
  const busy = saving || deleting

  useBeforeUnloadWarning(dirty)

  // De bevestiging na opslaan verdwijnt vanzelf; foutmeldingen blijven staan.
  useEffect(() => {
    if (feedback?.type !== "success") return
    const timer = window.setTimeout(() => setFeedback(null), SUCCESS_VISIBLE_MS)
    return () => window.clearTimeout(timer)
  }, [feedback])

  const save = async () => {
    const invalid = validate(form)
    if (invalid) {
      setFeedback({ type: "error", message: invalid })
      return
    }

    setFeedback(null)
    setSaving(true)
    try {
      const response = await fetch(`/api/customers/${encodeURIComponent(saved.id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(toPayload(form)),
      })
      const payload = (await response.json().catch(() => null)) as
        | (Partial<CustomerWebsiteDetail> & ErrorResponse)
        | null
      if (!response.ok) {
        throw new Error(getErrorMessage(payload, "Kon klant niet bijwerken."))
      }

      // Het antwoord bevat niet alle velden van het detail (zoals de tellers): aanvullen.
      const knowsProfile = !!payload && "profile" in payload
      const next: CustomerWebsiteDetail = {
        ...saved,
        ...payload,
        profile: knowsProfile ? parseProfile(payload?.profile) : saved.profile,
      }
      setSaved(next)
      if (knowsProfile) {
        setForm(toForm(next))
        setOpenCards(new Set())
        setFeedback({ type: "success", message: "Klantprofiel opgeslagen." })
      } else {
        // Oudere backend: de klantvelden zijn bewaard, het profiel niet. Invoer laten staan.
        setFeedback({
          type: "error",
          message:
            "Naam, website, toon en traject zijn opgeslagen, maar de backend kent het klantprofiel nog niet: de profielvelden zijn niet bewaard.",
        })
      }
      router.refresh()
    } catch (error) {
      setFeedback({
        type: "error",
        message: error instanceof Error ? error.message : "Kon klant niet bijwerken.",
      })
    } finally {
      setSaving(false)
    }
  }

  const deleteCustomer = async () => {
    const confirmed = window.confirm(
      `Klant "${saved.name}" definitief verwijderen? Keywords, scans en meta runs worden ook verwijderd. Blogs blijven bestaan maar verliezen hun klantkoppeling.`
    )
    if (!confirmed) return

    setFeedback(null)
    setDeleting(true)
    try {
      const response = await fetch(`/api/customers/${encodeURIComponent(saved.id)}`, {
        method: "DELETE",
      })
      const payload = (await response.json().catch(() => null)) as ErrorResponse | null
      if (!response.ok) {
        throw new Error(getErrorMessage(payload, "Kon klant niet verwijderen."))
      }
      router.push("/dashboard/klanten")
      router.refresh()
    } catch (error) {
      setFeedback({
        type: "error",
        message: error instanceof Error ? error.message : "Kon klant niet verwijderen.",
      })
      setDeleting(false)
    }
  }

  const updatedAt = formatShortDate(saved.updated_at)
  const categoryName =
    form.categoryId === (saved.category_id ?? "")
      ? saved.category_name
      : form.categoryId
        ? "Gewijzigd – wordt bij opslaan bewaard"
        : null

  return (
    <div className="space-y-6">
      <ProfielHeader
        crumbs={[
          { label: "Klanten", href: "/dashboard/klanten" },
          { label: saved.name, href: `/dashboard/klanten/${encodeURIComponent(saved.id)}` },
          { label: "Profiel" },
        ]}
        title={`Klantprofiel – ${saved.name}`}
        subtitle={
          <>
            Wordt meegegeven aan Claude bij content briefs en concepteksten
            {updatedAt && ` · laatst bijgewerkt ${updatedAt}`}
          </>
        }
        actions={
          <>
            {dirty && !saving && <UnsavedNotice />}
            <AiFillButton />
            <Button onClick={() => void save()} disabled={!dirty || busy}>
              {saving && <Loader2 className="animate-spin" aria-hidden="true" />}
              {saving ? "Opslaan…" : "Opslaan"}
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
        categoryName={categoryName}
        connections={connections}
      />

      <KlantVerwijderen onDelete={() => void deleteCustomer()} deleting={deleting} disabled={busy} />
    </div>
  )
}
