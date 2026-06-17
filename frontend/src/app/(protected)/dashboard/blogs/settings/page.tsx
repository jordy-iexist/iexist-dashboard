"use client";

import { useEffect, useState, useTransition } from "react";
import { WordPressSitesSettings } from "@/components/settings/WordPressSitesSettings";

type BlogGenerationSettings = {
  system_prompt: string | null;
  reasoning_effort: string | null;
  model: string | null;
  max_output_tokens: number | null;
  image_style_instruction: string | null;
  image_size: string | null;
  image_model: string | null;
  image_quality: string | null;
  image_output_format: string | null;
  image_output_compression: number | null;
  effective_system_prompt: string;
  effective_reasoning_effort: string;
  effective_model: string;
  effective_max_output_tokens: number;
  effective_image_style_instruction: string;
  effective_image_size: string;
  effective_image_model: string;
  effective_image_quality: string;
  effective_image_output_format: string;
  effective_image_output_compression: number;
};

export default function BlogGeneratorSettingsPage() {
  const [settings, setSettings] = useState<BlogGenerationSettings | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [systemPrompt, setSystemPrompt] = useState("");
  const [reasoningEffort, setReasoningEffort] = useState("");
  const [model, setModel] = useState("");
  const [maxOutputTokens, setMaxOutputTokens] = useState("");

  const [imageStyleInstruction, setImageStyleInstruction] = useState("");
  const [imageSize, setImageSize] = useState("");
  const [imageModel, setImageModel] = useState("");
  const [imageQuality, setImageQuality] = useState("");
  const [imageOutputFormat, setImageOutputFormat] = useState("");
  const [imageOutputCompression, setImageOutputCompression] = useState("");

  const [saveSuccess, setSaveSuccess] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    fetch("/api/blogs/settings")
      .then((r) => r.json())
      .then((data) => {
        if (data.error) {
          setLoadError(data.error);
          return;
        }
        const s = data as BlogGenerationSettings;
        setSettings(s);
        setSystemPrompt(s.system_prompt ?? "");
        setReasoningEffort(s.reasoning_effort ?? "");
        setModel(s.model ?? "");
        setMaxOutputTokens(
          s.max_output_tokens != null ? String(s.max_output_tokens) : "",
        );
        setImageStyleInstruction(s.image_style_instruction ?? "");
        setImageSize(s.image_size ?? "");
        setImageModel(s.image_model ?? "");
        setImageQuality(s.image_quality ?? "");
        setImageOutputFormat(s.image_output_format ?? "");
        setImageOutputCompression(
          s.image_output_compression != null
            ? String(s.image_output_compression)
            : "",
        );
      })
      .catch(() => setLoadError("Kon instellingen niet laden."));
  }, []);

  function handleSave() {
    setSaveSuccess(false);
    setSaveError(null);

    const parsedTokens =
      maxOutputTokens.trim() !== "" ? parseInt(maxOutputTokens, 10) : null;
    const parsedCompression =
      imageOutputCompression.trim() !== ""
        ? parseInt(imageOutputCompression, 10)
        : null;

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
        });
        const data = await response.json();
        if (!response.ok || data.error) {
          setSaveError(data.error ?? "Opslaan mislukt.");
          return;
        }
        setSettings(data as BlogGenerationSettings);
        setSaveSuccess(true);
      } catch {
        setSaveError("Interne fout bij opslaan.");
      }
    });
  }

  if (loadError) {
    return (
      <div className="rounded-lg border border-destructive p-4 text-sm text-destructive">
        {loadError}
      </div>
    );
  }

  if (!settings) {
    return (
      <p className="text-sm text-muted-foreground">Instellingen laden...</p>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">
          Blog Generator Instellingen
        </h1>
        <p className="text-muted-foreground">
          Pas de AI-parameters aan voor jouw blog generatie. Lege velden
          gebruiken de systeemstandaard.
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
            min={1}
            className="w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            placeholder={String(settings.effective_max_output_tokens)}
            value={maxOutputTokens}
            onChange={(e) => setMaxOutputTokens(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">
            Leeg laten voor standaard: {settings.effective_max_output_tokens}
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

      <div className="rounded-lg border p-6 space-y-6">
        <div>
          <h2 className="text-xl font-semibold tracking-tight">
            Afbeeldingsgeneratie
          </h2>
          <p className="text-sm text-muted-foreground">
            Instellingen voor de automatisch gegenereerde hero-/uitgelichte
            afbeelding (16:9). Lege velden gebruiken de systeemstandaard.
          </p>
        </div>

        {/* Style instruction */}
        <div className="space-y-2">
          <label className="text-sm font-medium" htmlFor="image-style">
            Stijl-instructie
          </label>
          <textarea
            id="image-style"
            className="w-full rounded-md border bg-background px-3 py-2 text-sm min-h-32 resize-y focus:outline-none focus:ring-2 focus:ring-ring"
            placeholder={settings.effective_image_style_instruction}
            value={imageStyleInstruction}
            onChange={(e) => setImageStyleInstruction(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">
            De blogtitel en een samenvatting worden automatisch toegevoegd. Leeg
            laten om de systeemstandaard te gebruiken.
          </p>
        </div>

        {/* Image size */}
        <div className="space-y-2">
          <label className="text-sm font-medium" htmlFor="image-size">
            Afbeeldingsgrootte
          </label>
          <select
            id="image-size"
            className="w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
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
        </div>

        {/* Image model */}
        <div className="space-y-2">
          <label className="text-sm font-medium" htmlFor="image-model">
            Model
          </label>
          <input
            id="image-model"
            type="text"
            className="w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            placeholder={settings.effective_image_model}
            value={imageModel}
            onChange={(e) => setImageModel(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">
            Leeg laten voor standaard: {settings.effective_image_model}
          </p>
        </div>

        {/* Image quality */}
        <div className="space-y-2">
          <label className="text-sm font-medium" htmlFor="image-quality">
            Kwaliteit
          </label>
          <select
            id="image-quality"
            className="w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
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
        </div>

        {/* Output format */}
        <div className="space-y-2">
          <label className="text-sm font-medium" htmlFor="image-output-format">
            Uitvoerformaat
          </label>
          <select
            id="image-output-format"
            className="w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
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
        </div>

        {/* Output compression */}
        <div className="space-y-2">
          <label
            className="text-sm font-medium"
            htmlFor="image-output-compression"
          >
            Compressie (0–100)
          </label>
          <input
            id="image-output-compression"
            type="number"
            min={0}
            max={100}
            className="w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            placeholder={String(settings.effective_image_output_compression)}
            value={imageOutputCompression}
            onChange={(e) => setImageOutputCompression(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">
            Alleen van toepassing op jpeg/webp. Lager = kleiner bestand, minder
            detail. Leeg laten voor standaard:{" "}
            {settings.effective_image_output_compression}.
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

      <WordPressSitesSettings />
    </div>
  );
}
