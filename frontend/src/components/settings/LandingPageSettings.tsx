"use client"

import { useEffect, useState, useTransition } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  SettingsFeedback,
  SettingsField,
  SettingsSection,
  fieldClassName,
} from "@/components/settings/SettingsSection"
import { type LandingPageGenerationSettings } from "@/lib/landing-page-types"

const MIN_MAX_OUTPUT_TOKENS = 1000
const MAX_MAX_OUTPUT_TOKENS = 50000

export function LandingPageSettings() {
  const [settings, setSettings] = useState<LandingPageGenerationSettings | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  const [systemPrompt, setSystemPrompt] = useState("")
  const [reasoningEffort, setReasoningEffort] = useState("")
  const [model, setModel] = useState("")
  const [maxOutputTokens, setMaxOutputTokens] = useState("")

  const [saveSuccess, setSaveSuccess] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [isPending, startTransition] = useTransition()

  useEffect(() => {
    fetch("/api/landing-pages/settings")
      .then((r) => r.json())
      .then((data: unknown) => {
        if (data && typeof data === "object" && "error" in data) {
          setLoadError((data as { error: string }).error)
          return
        }
        const s = data as LandingPageGenerationSettings
        setSettings(s)
        setSystemPrompt(s.system_prompt ?? "")
        setReasoningEffort(s.reasoning_effort ?? "")
        setModel(s.model ?? "")
        setMaxOutputTokens(
          s.max_output_tokens != null ? String(s.max_output_tokens) : ""
        )
      })
      .catch(() => setLoadError("Kon instellingen niet laden."))
  }, [])

  function handleSave() {
    setSaveSuccess(false)
    setSaveError(null)

    const parsedTokens =
      maxOutputTokens.trim() !== "" ? parseInt(maxOutputTokens, 10) : null

    startTransition(async () => {
      try {
        const response = await fetch("/api/landing-pages/settings", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            system_prompt: systemPrompt.trim() || null,
            reasoning_effort: reasoningEffort || null,
            model: model.trim() || null,
            max_output_tokens:
              parsedTokens !== null && !isNaN(parsedTokens) ? parsedTokens : null,
          }),
        })
        const data = await response.json()
        if (!response.ok || (data && typeof data === "object" && "error" in data)) {
          setSaveError(
            (data as { error?: string }).error ?? "Opslaan mislukt."
          )
          return
        }
        setSettings(data as LandingPageGenerationSettings)
        setSaveSuccess(true)
      } catch {
        setSaveError("Interne fout bij opslaan.")
      }
    })
  }

  if (loadError) {
    return <SettingsFeedback type="error">{loadError}</SettingsFeedback>
  }

  if (!settings) {
    return <p className="text-sm text-muted-foreground">Instellingen laden...</p>
  }

  return (
    <div>
      <SettingsSection
        title="Tekstgeneratie"
        description="Prompt en model waarmee landingspagina's geschreven worden."
      >
        <SettingsField
          label="Systemprompt"
          htmlFor="system-prompt"
          hint="Leeg laten om de systeemstandaard te gebruiken."
        >
          <textarea
            id="system-prompt"
            className={`${fieldClassName} min-h-48 resize-y`}
            placeholder={settings.effective_system_prompt}
            value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)}
          />
        </SettingsField>

        <div className="grid gap-5 sm:grid-cols-2">
          <SettingsField label="Model" htmlFor="model">
            <Input
              id="model"
              placeholder={settings.effective_model}
              value={model}
              onChange={(e) => setModel(e.target.value)}
            />
          </SettingsField>

          <SettingsField label="Reasoning effort" htmlFor="reasoning-effort">
            <select
              id="reasoning-effort"
              className={fieldClassName}
              value={reasoningEffort}
              onChange={(e) => setReasoningEffort(e.target.value)}
            >
              <option value="">
                Standaard ({settings.effective_reasoning_effort})
              </option>
              <option value="low">low</option>
              <option value="medium">medium</option>
              <option value="high">high</option>
            </select>
          </SettingsField>

          <SettingsField
            label="Max output tokens"
            htmlFor="max-output-tokens"
            hint={`Standaard: ${settings.effective_max_output_tokens}. Toegestaan: ${MIN_MAX_OUTPUT_TOKENS} tot ${MAX_MAX_OUTPUT_TOKENS}.`}
          >
            <Input
              id="max-output-tokens"
              type="number"
              min={MIN_MAX_OUTPUT_TOKENS}
              max={MAX_MAX_OUTPUT_TOKENS}
              placeholder={String(settings.effective_max_output_tokens)}
              value={maxOutputTokens}
              onChange={(e) => setMaxOutputTokens(e.target.value)}
            />
          </SettingsField>
        </div>
      </SettingsSection>

      <div className="flex flex-wrap items-center justify-end gap-3 border-t pt-6">
        {saveSuccess && (
          <p className="text-sm text-green-700">Instellingen opgeslagen.</p>
        )}
        {saveError && <p className="text-sm text-red-700">{saveError}</p>}
        <Button onClick={handleSave} disabled={isPending}>
          {isPending ? "Opslaan..." : "Opslaan"}
        </Button>
      </div>
    </div>
  )
}
