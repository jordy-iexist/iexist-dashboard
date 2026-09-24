"use client"

import { useEffect, useState, useTransition } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  SettingsFeedback,
  SettingsField,
  SettingsSection,
} from "@/components/settings/SettingsSection"

type OpenAISettingsResponse =
  | {
      has_personal_openai_api_key: boolean
    }
  | {
      error: string
    }

function getErrorMessage(payload: unknown, fallback: string) {
  if (!payload || typeof payload !== "object") {
    return fallback
  }

  const error = (payload as { error?: unknown }).error
  if (typeof error === "string" && error.trim().length > 0) {
    return error
  }

  return fallback
}

export function OpenAISettings() {
  const [hasPersonalKey, setHasPersonalKey] = useState(false)
  const [apiKey, setApiKey] = useState("")
  const [isLoading, setIsLoading] = useState(true)
  const [feedback, setFeedback] = useState<{
    type: "success" | "error" | null
    message: string
  }>({ type: null, message: "" })
  const [isPending, startTransition] = useTransition()

  useEffect(() => {
    const loadSettings = async () => {
      setIsLoading(true)

      try {
        const response = await fetch("/api/settings/openai", {
          method: "GET",
          cache: "no-store",
        })
        const payload = (await response.json().catch(() => null)) as
          | OpenAISettingsResponse
          | null

        if (!response.ok) {
          throw new Error(
            getErrorMessage(payload, "Kon OpenAI instellingen niet ophalen.")
          )
        }

        setHasPersonalKey(
          Boolean(
            payload &&
              "has_personal_openai_api_key" in payload &&
              payload.has_personal_openai_api_key
          )
        )
      } catch (error) {
        setFeedback({
          type: "error",
          message:
            error instanceof Error
              ? error.message
              : "Kon OpenAI instellingen niet ophalen.",
        })
      } finally {
        setIsLoading(false)
      }
    }

    loadSettings()
  }, [])

  const refreshSettings = async () => {
    const response = await fetch("/api/settings/openai", {
      method: "GET",
      cache: "no-store",
    })
    const payload = (await response.json().catch(() => null)) as
      | OpenAISettingsResponse
      | null

    if (!response.ok) {
      throw new Error(
        getErrorMessage(payload, "Kon OpenAI instellingen niet ophalen.")
      )
    }

    setHasPersonalKey(
      Boolean(
        payload &&
          "has_personal_openai_api_key" in payload &&
          payload.has_personal_openai_api_key
      )
    )
  }

  const saveKey = () => {
    const trimmedKey = apiKey.trim()
    if (!trimmedKey) {
      setFeedback({
        type: "error",
        message: "Vul eerst een OpenAI API key in.",
      })
      return
    }

    setFeedback({ type: null, message: "" })
    startTransition(async () => {
      try {
        const response = await fetch("/api/settings/openai", {
          method: "PUT",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ openai_api_key: trimmedKey }),
        })
        const payload = (await response.json().catch(() => null)) as
          | OpenAISettingsResponse
          | null

        if (!response.ok) {
          throw new Error(
            getErrorMessage(payload, "Kon OpenAI API key niet opslaan.")
          )
        }

        setApiKey("")
        await refreshSettings()
        setFeedback({
          type: "success",
          message: "OpenAI API key opgeslagen.",
        })
      } catch (error) {
        setFeedback({
          type: "error",
          message:
            error instanceof Error
              ? error.message
              : "Kon OpenAI API key niet opslaan.",
        })
      }
    })
  }

  const removeKey = () => {
    setFeedback({ type: null, message: "" })
    startTransition(async () => {
      try {
        const response = await fetch("/api/settings/openai", {
          method: "PUT",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ openai_api_key: null }),
        })
        const payload = (await response.json().catch(() => null)) as
          | OpenAISettingsResponse
          | null

        if (!response.ok) {
          throw new Error(
            getErrorMessage(payload, "Kon OpenAI API key niet verwijderen.")
          )
        }

        setApiKey("")
        await refreshSettings()
        setFeedback({
          type: "success",
          message: "OpenAI API key verwijderd.",
        })
      } catch (error) {
        setFeedback({
          type: "error",
          message:
            error instanceof Error
              ? error.message
              : "Kon OpenAI API key niet verwijderen.",
        })
      }
    })
  }

  return (
    <div>
      <SettingsSection
        title="Status"
        description="De opgeslagen key wordt niet teruggetoond."
      >
        {feedback.type && (
          <SettingsFeedback type={feedback.type}>{feedback.message}</SettingsFeedback>
        )}

        <p className="text-sm text-muted-foreground">
          {isLoading
            ? "Instellingen laden..."
            : hasPersonalKey
            ? "Persoonlijke OpenAI API key ingesteld."
            : "Nog geen persoonlijke OpenAI API key ingesteld."}
        </p>
      </SettingsSection>

      <SettingsSection
        title="Key instellen"
        description="Opslaan vervangt de bestaande key direct."
      >
        <SettingsField label="Nieuwe OpenAI API key" htmlFor="openai-api-key">
          <Input
            id="openai-api-key"
            type="password"
            autoComplete="off"
            placeholder={hasPersonalKey ? "Vervang bestaande key" : "sk-..."}
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
          />
        </SettingsField>

        <div className="flex flex-wrap gap-3">
          <Button
            onClick={saveKey}
            disabled={isPending || apiKey.trim().length === 0}
          >
            {isPending ? "Opslaan..." : hasPersonalKey ? "Key bijwerken" : "Key opslaan"}
          </Button>
          <Button
            variant="outline"
            onClick={() => setApiKey("")}
            disabled={isPending || apiKey.length === 0}
          >
            Veld leegmaken
          </Button>
        </div>
      </SettingsSection>

      <SettingsSection
        title="Key verwijderen"
        description="Verwijdert je persoonlijke key van je account."
      >
        <div>
          <Button
            variant="destructive"
            onClick={removeKey}
            disabled={isPending || !hasPersonalKey}
          >
            Key verwijderen
          </Button>
        </div>
      </SettingsSection>
    </div>
  )
}
