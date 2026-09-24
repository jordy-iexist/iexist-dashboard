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

type BlogGenerationSettingsResponse = {
  system_prompt: string | null
  reasoning_effort: string | null
  model: string | null
  max_output_tokens: number | null
  image_style_instruction: string | null
  image_size: string | null
  image_model: string | null
  image_quality: string | null
  image_output_format: string | null
  image_output_compression: number | null
  effective_system_prompt: string
  effective_reasoning_effort: string
  effective_model: string
  effective_max_output_tokens: number
  effective_image_style_instruction: string
  effective_image_size: string
  effective_image_model: string
  effective_image_quality: string
  effective_image_output_format: string
  effective_image_output_compression: number
}

export function BlogGenerationSettings() {
  const [settings, setSettings] =
    useState<BlogGenerationSettingsResponse | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  const [systemPrompt, setSystemPrompt] = useState("")
  const [reasoningEffort, setReasoningEffort] = useState("")
  const [model, setModel] = useState("")
  const [maxOutputTokens, setMaxOutputTokens] = useState("")

  const [imageStyleInstruction, setImageStyleInstruction] = useState("")
  const [imageSize, setImageSize] = useState("")
  const [imageModel, setImageModel] = useState("")
  const [imageQuality, setImageQuality] = useState("")
  const [imageOutputFormat, setImageOutputFormat] = useState("")
  const [imageOutputCompression, setImageOutputCompression] = useState("")

  const [saveSuccess, setSaveSuccess] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [isPending, startTransition] = useTransition()

  useEffect(() => {
    fetch("/api/blogs/settings")
      .then((r) => r.json())
      .then((data) => {
        if (data.error) {
          setLoadError(data.error)
          return
        }
        const s = data as BlogGenerationSettingsResponse
        setSettings(s)
        setSystemPrompt(s.system_prompt ?? "")
        setReasoningEffort(s.reasoning_effort ?? "")
        setModel(s.model ?? "")
        setMaxOutputTokens(
          s.max_output_tokens != null ? String(s.max_output_tokens) : ""
        )
        setImageStyleInstruction(s.image_style_instruction ?? "")
        setImageSize(s.image_size ?? "")
        setImageModel(s.image_model ?? "")
        setImageQuality(s.image_quality ?? "")
        setImageOutputFormat(s.image_output_format ?? "")
        setImageOutputCompression(
          s.image_output_compression != null
            ? String(s.image_output_compression)
            : ""
        )
      })
      .catch(() => setLoadError("Kon instellingen niet laden."))
  }, [])

  function handleSave() {
    setSaveSuccess(false)
    setSaveError(null)

    const parsedTokens =
      maxOutputTokens.trim() !== "" ? parseInt(maxOutputTokens, 10) : null
    const parsedCompression =
      imageOutputCompression.trim() !== ""
        ? parseInt(imageOutputCompression, 10)
        : null

    startTransition(async () => {
      try {
        const response = await fetch("/api/blogs/settings", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            system_prompt: systemPrompt.trim() || null,
            reasoning_effort: reasoningEffort || null,
            model: model.trim() || null,
            max_output_tokens:
              parsedTokens !== null && !isNaN(parsedTokens)
                ? parsedTokens
                : null,
            image_style_instruction: imageStyleInstruction.trim() || null,
            image_size: imageSize || null,
            image_model: imageModel.trim() || null,
            image_quality: imageQuality || null,
            image_output_format: imageOutputFormat || null,
            image_output_compression:
              parsedCompression !== null && !isNaN(parsedCompression)
                ? parsedCompression
                : null,
          }),
        })
        const data = await response.json()
        if (!response.ok || data.error) {
          setSaveError(data.error ?? "Opslaan mislukt.")
          return
        }
        setSettings(data as BlogGenerationSettingsResponse)
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
        description="Prompt en model waarmee de blogtekst geschreven wordt."
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
            hint={`Standaard: ${settings.effective_max_output_tokens}`}
          >
            <Input
              id="max-output-tokens"
              type="number"
              min={1}
              placeholder={String(settings.effective_max_output_tokens)}
              value={maxOutputTokens}
              onChange={(e) => setMaxOutputTokens(e.target.value)}
            />
          </SettingsField>
        </div>
      </SettingsSection>

      <SettingsSection
        title="Afbeeldingen"
        description="De automatisch gegenereerde hero-/uitgelichte afbeelding (16:9)."
      >
        <SettingsField
          label="Stijl-instructie"
          htmlFor="image-style"
          hint="De blogtitel en een samenvatting worden automatisch toegevoegd. Leeg laten om de systeemstandaard te gebruiken."
        >
          <textarea
            id="image-style"
            className={`${fieldClassName} min-h-32 resize-y`}
            placeholder={settings.effective_image_style_instruction}
            value={imageStyleInstruction}
            onChange={(e) => setImageStyleInstruction(e.target.value)}
          />
        </SettingsField>

        <div className="grid gap-5 sm:grid-cols-2">
          <SettingsField label="Model" htmlFor="image-model">
            <Input
              id="image-model"
              placeholder={settings.effective_image_model}
              value={imageModel}
              onChange={(e) => setImageModel(e.target.value)}
            />
          </SettingsField>

          <SettingsField label="Afbeeldingsgrootte" htmlFor="image-size">
            <select
              id="image-size"
              className={fieldClassName}
              value={imageSize}
              onChange={(e) => setImageSize(e.target.value)}
            >
              <option value="">
                Standaard ({settings.effective_image_size})
              </option>
              <option value="2048x1152">2048×1152 (16:9)</option>
              <option value="3840x2160">3840×2160 (16:9, 4K)</option>
              <option value="1536x1024">1536×1024 (3:2)</option>
            </select>
          </SettingsField>

          <SettingsField label="Kwaliteit" htmlFor="image-quality">
            <select
              id="image-quality"
              className={fieldClassName}
              value={imageQuality}
              onChange={(e) => setImageQuality(e.target.value)}
            >
              <option value="">
                Standaard ({settings.effective_image_quality})
              </option>
              <option value="auto">auto</option>
              <option value="low">low</option>
              <option value="medium">medium</option>
              <option value="high">high</option>
            </select>
          </SettingsField>

          <SettingsField label="Uitvoerformaat" htmlFor="image-output-format">
            <select
              id="image-output-format"
              className={fieldClassName}
              value={imageOutputFormat}
              onChange={(e) => setImageOutputFormat(e.target.value)}
            >
              <option value="">
                Standaard ({settings.effective_image_output_format})
              </option>
              <option value="jpeg">jpeg (kleiner bestand)</option>
              <option value="webp">webp (kleinst)</option>
              <option value="png">png (grootst, lossless)</option>
            </select>
          </SettingsField>

          <SettingsField
            label="Compressie (0–100)"
            htmlFor="image-output-compression"
            hint={`Alleen voor jpeg/webp. Lager = kleiner bestand. Standaard: ${settings.effective_image_output_compression}`}
          >
            <Input
              id="image-output-compression"
              type="number"
              min={0}
              max={100}
              placeholder={String(settings.effective_image_output_compression)}
              value={imageOutputCompression}
              onChange={(e) => setImageOutputCompression(e.target.value)}
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
