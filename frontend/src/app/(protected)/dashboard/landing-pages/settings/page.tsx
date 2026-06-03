"use client"

import { useEffect, useState, useTransition } from "react"

import { type LandingPageGenerationSettings } from "@/lib/landing-page-types"

const MIN_MAX_OUTPUT_TOKENS = 1000
const MAX_MAX_OUTPUT_TOKENS = 50000

export default function LandingPageSettingsPage() {
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
    return (
      <div className="rounded-lg border border-destructive p-4 text-sm text-destructive">
        {loadError}
      </div>
    )
  }

  if (!settings) {
    return (
      <p className="text-sm text-muted-foreground">Instellingen laden...</p>
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">
          Landingspagina instellingen
        </h1>
        <p className="text-muted-foreground">
          Pas het systeem prompt en model aan voor landingspagina generatie
        </p>
      </div>

      {saveSuccess && (
        <div className="rounded-lg border border-green-500 bg-green-50 p-4 text-sm text-green-700">
          Instellingen opgeslagen.
        </div>
      )}
      {saveError && (
        <div className="rounded-lg border border-destructive bg-red-50 p-4 text-sm text-destructive">
          {saveError}
        </div>
      )}

      <div className="rounded-lg border p-6 space-y-6">
        {/* System Prompt */}
        <div className="space-y-2">
          <label className="text-sm font-medium" htmlFor="system-prompt">
            Systemprompt
          </label>
          <textarea
            id="system-prompt"
            className="w-full rounded-md border bg-background px-3 py-2 text-sm min-h-48 resize-y focus:outline-none focus:ring-2 focus:ring-ring"
            placeholder={settings.effective_system_prompt}
            value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">
            Leeg laten om de systeemstandaard te gebruiken.
          </p>
        </div>

        {/* Reasoning Effort */}
        <div className="space-y-2">
          <label className="text-sm font-medium" htmlFor="reasoning-effort">
            Reasoning Effort
          </label>
          <select
            id="reasoning-effort"
            className="w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
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
        </div>

        {/* Model */}
        <div className="space-y-2">
          <label className="text-sm font-medium" htmlFor="model">
            Model
          </label>
          <input
            id="model"
            type="text"
            className="w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            placeholder={settings.effective_model}
            value={model}
            onChange={(e) => setModel(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">
            Leeg laten voor standaard: {settings.effective_model}
          </p>
        </div>

        {/* Max Output Tokens */}
        <div className="space-y-2">
          <label className="text-sm font-medium" htmlFor="max-output-tokens">
            Max Output Tokens
          </label>
          <input
            id="max-output-tokens"
            type="number"
            min={MIN_MAX_OUTPUT_TOKENS}
            max={MAX_MAX_OUTPUT_TOKENS}
            className="w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            placeholder={String(settings.effective_max_output_tokens)}
            value={maxOutputTokens}
            onChange={(e) => setMaxOutputTokens(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">
            Leeg laten voor standaard: {settings.effective_max_output_tokens}. Toegestaan: {MIN_MAX_OUTPUT_TOKENS} tot {MAX_MAX_OUTPUT_TOKENS}.
          </p>
        </div>

        <button
          onClick={handleSave}
          disabled={isPending}
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          {isPending ? "Opslaan..." : "Opslaan"}
        </button>
      </div>
    </div>
  )
}
