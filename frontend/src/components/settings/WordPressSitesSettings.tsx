"use client"

import { useCallback, useEffect, useMemo, useState, useTransition } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  SettingsFeedback,
  SettingsSection,
} from "@/components/settings/SettingsSection"
import { WordPressSite } from "@/lib/wordpress-types"

type SitesApiResponse =
  | {
      sites: WordPressSite[]
    }
  | {
      error: string
    }

type SiteResponse =
  | WordPressSite
  | {
      error: string
    }

type SiteFormState = {
  name: string
  baseUrl: string
  wpLogin: string
  wpPassword: string
}

type EditFormState = {
  name: string
  baseUrl: string
  wpLogin: string
  wpPassword: string
  isActive: boolean
}

function formatDate(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return "-"
  }

  return new Intl.DateTimeFormat("nl-NL", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date)
}

function createEmptySiteForm(): SiteFormState {
  return {
    name: "",
    baseUrl: "",
    wpLogin: "",
    wpPassword: "",
  }
}

function createEditForm(site: WordPressSite): EditFormState {
  return {
    name: site.name,
    baseUrl: site.base_url,
    wpLogin: site.wp_login,
    wpPassword: "",
    isActive: site.is_active,
  }
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

export function WordPressSitesSettings() {
  const [sites, setSites] = useState<WordPressSite[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [feedback, setFeedback] = useState<{
    type: "success" | "error" | null
    message: string
  }>({ type: null, message: "" })
  const [addForm, setAddForm] = useState<SiteFormState>(createEmptySiteForm)
  const [editingSiteId, setEditingSiteId] = useState<string | null>(null)
  const [editForm, setEditForm] = useState<EditFormState | null>(null)
  const [isPending, startTransition] = useTransition()

  const sortedSites = useMemo(
    () =>
      [...sites].sort((a, b) => {
        return (
          new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
        )
      }),
    [sites]
  )

  const loadSites = useCallback(async () => {
    setIsLoading(true)
    try {
      const response = await fetch("/api/wordpress/sites", {
        method: "GET",
        cache: "no-store",
      })
      const payload = (await response.json().catch(() => null)) as
        | SitesApiResponse
        | null
      if (!response.ok) {
        throw new Error(
          getErrorMessage(payload, "Kon WordPress sites niet ophalen.")
        )
      }

      const nextSites =
        payload && "sites" in payload && Array.isArray(payload.sites)
          ? payload.sites
          : []
      setSites(nextSites)
    } catch (error) {
      setFeedback({
        type: "error",
        message:
          error instanceof Error
            ? error.message
            : "Kon WordPress sites niet ophalen.",
      })
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    loadSites()
  }, [loadSites])

  const addSite = () => {
    setFeedback({ type: null, message: "" })
    startTransition(async () => {
      try {
        const response = await fetch("/api/wordpress/sites", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            name: addForm.name.trim() || null,
            base_url: addForm.baseUrl.trim(),
            wp_login: addForm.wpLogin.trim(),
            wp_password: addForm.wpPassword,
          }),
        })
        const payload = (await response.json().catch(() => null)) as
          | SiteResponse
          | null
        if (!response.ok) {
          throw new Error(getErrorMessage(payload, "Kon WordPress site niet toevoegen."))
        }
        if (!payload || !("id" in payload)) {
          throw new Error("Onverwachte response van server.")
        }

        setAddForm(createEmptySiteForm())
        setFeedback({
          type: "success",
          message: "WordPress site is toegevoegd.",
        })
        await loadSites()
      } catch (error) {
        setFeedback({
          type: "error",
          message:
            error instanceof Error
              ? error.message
              : "Kon WordPress site niet toevoegen.",
        })
      }
    })
  }

  const startEditing = (site: WordPressSite) => {
    setEditingSiteId(site.id)
    setEditForm(createEditForm(site))
    setFeedback({ type: null, message: "" })
  }

  const cancelEditing = () => {
    setEditingSiteId(null)
    setEditForm(null)
  }

  const saveEdit = (siteId: string) => {
    if (!editForm) {
      return
    }

    setFeedback({ type: null, message: "" })
    startTransition(async () => {
      try {
        const response = await fetch(`/api/wordpress/sites/${siteId}`, {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            name: editForm.name.trim(),
            base_url: editForm.baseUrl.trim(),
            wp_login: editForm.wpLogin.trim(),
            wp_password: editForm.wpPassword.trim() || undefined,
            is_active: editForm.isActive,
          }),
        })
        const payload = (await response.json().catch(() => null)) as
          | SiteResponse
          | null

        if (!response.ok) {
          throw new Error(getErrorMessage(payload, "Kon WordPress site niet updaten."))
        }

        setEditingSiteId(null)
        setEditForm(null)
        setFeedback({
          type: "success",
          message: "WordPress site is bijgewerkt.",
        })
        await loadSites()
      } catch (error) {
        setFeedback({
          type: "error",
          message:
            error instanceof Error
              ? error.message
              : "Kon WordPress site niet updaten.",
        })
      }
    })
  }

  return (
    <div>
      {feedback.message && (
        <div className="mb-6">
          <SettingsFeedback type={feedback.type === "success" ? "success" : "error"}>
            {feedback.message}
          </SettingsFeedback>
        </div>
      )}

      <SettingsSection
        title="Gekoppelde sites"
        description="Alleen actieve sites zijn beschikbaar bij het publiceren."
      >
        {isLoading && (
          <p className="text-sm text-muted-foreground">WordPress sites laden...</p>
        )}

        {!isLoading && sortedSites.length === 0 && (
          <p className="text-sm text-muted-foreground">
            Nog geen WordPress sites gekoppeld.
          </p>
        )}

        {!isLoading && sortedSites.length > 0 && (
          <ul className="divide-y border-y">
            {sortedSites.map((site) => {
              const isEditing = editingSiteId === site.id && editForm
              return (
                <li key={site.id} className="space-y-4 py-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 space-y-0.5">
                      <p className="text-sm font-medium">{site.name}</p>
                      <p className="truncate text-xs text-muted-foreground">
                        {site.base_url} · {site.wp_login}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        Toegevoegd: {formatDate(site.created_at)}
                      </p>
                    </div>

                    <div className="flex items-center gap-3">
                      <span
                        className={`inline-flex items-center gap-1.5 text-xs ${
                          site.is_active ? "text-green-700" : "text-muted-foreground"
                        }`}
                      >
                        <span
                          className={`size-1.5 rounded-full ${
                            site.is_active ? "bg-green-600" : "bg-zinc-400"
                          }`}
                        />
                        {site.is_active ? "Actief" : "Inactief"}
                      </span>
                      {!isEditing && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => startEditing(site)}
                          disabled={isPending}
                        >
                          Bewerk
                        </Button>
                      )}
                    </div>
                  </div>

                  {isEditing && editForm && (
                    <div className="space-y-4">
                      <div className="grid gap-3 md:grid-cols-2">
                        <div className="space-y-1">
                          <label className="text-xs font-medium">Naam</label>
                          <Input
                            value={editForm.name}
                            onChange={(event) =>
                              setEditForm((current) =>
                                current
                                  ? { ...current, name: event.target.value }
                                  : current
                              )
                            }
                            disabled={isPending}
                          />
                        </div>
                        <div className="space-y-1">
                          <label className="text-xs font-medium">Site URL</label>
                          <Input
                            value={editForm.baseUrl}
                            onChange={(event) =>
                              setEditForm((current) =>
                                current
                                  ? { ...current, baseUrl: event.target.value }
                                  : current
                              )
                            }
                            disabled={isPending}
                          />
                        </div>
                        <div className="space-y-1">
                          <label className="text-xs font-medium">
                            WordPress login
                          </label>
                          <Input
                            value={editForm.wpLogin}
                            onChange={(event) =>
                              setEditForm((current) =>
                                current
                                  ? { ...current, wpLogin: event.target.value }
                                  : current
                              )
                            }
                            disabled={isPending}
                          />
                        </div>
                        <div className="space-y-1">
                          <label className="text-xs font-medium">
                            Nieuw wachtwoord (optioneel)
                          </label>
                          <Input
                            type="password"
                            value={editForm.wpPassword}
                            onChange={(event) =>
                              setEditForm((current) =>
                                current
                                  ? { ...current, wpPassword: event.target.value }
                                  : current
                              )
                            }
                            placeholder="Laat leeg om ongewijzigd te laten"
                            disabled={isPending}
                          />
                        </div>
                      </div>

                      <label className="inline-flex items-center gap-2 text-sm">
                        <input
                          type="checkbox"
                          checked={editForm.isActive}
                          onChange={(event) =>
                            setEditForm((current) =>
                              current
                                ? { ...current, isActive: event.target.checked }
                                : current
                            )
                          }
                          disabled={isPending}
                        />
                        Site actief
                      </label>

                      <div className="flex justify-end gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={cancelEditing}
                          disabled={isPending}
                        >
                          Annuleren
                        </Button>
                        <Button
                          size="sm"
                          onClick={() => saveEdit(site.id)}
                          disabled={
                            isPending ||
                            editForm.name.trim().length === 0 ||
                            editForm.baseUrl.trim().length === 0 ||
                            editForm.wpLogin.trim().length === 0
                          }
                        >
                          {isPending ? "Opslaan..." : "Opslaan"}
                        </Button>
                      </div>
                    </div>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </SettingsSection>

      <SettingsSection
        title="Nieuwe site toevoegen"
        description="Gebruik een WordPress Application Password, niet je gewone wachtwoord."
      >
        <div className="grid gap-3 md:grid-cols-2">
          <div className="space-y-1">
            <label className="text-xs font-medium">Naam (optioneel)</label>
            <Input
              placeholder="Bijv. Klantsite NL"
              value={addForm.name}
              onChange={(event) =>
                setAddForm((current) => ({ ...current, name: event.target.value }))
              }
              disabled={isPending}
            />
          </div>

          <div className="space-y-1">
            <label className="text-xs font-medium">Site URL</label>
            <Input
              placeholder="https://voorbeeld.nl"
              value={addForm.baseUrl}
              onChange={(event) =>
                setAddForm((current) => ({
                  ...current,
                  baseUrl: event.target.value,
                }))
              }
              disabled={isPending}
            />
          </div>

          <div className="space-y-1">
            <label className="text-xs font-medium">WordPress login</label>
            <Input
              placeholder="Gebruikersnaam of e-mail"
              value={addForm.wpLogin}
              onChange={(event) =>
                setAddForm((current) => ({
                  ...current,
                  wpLogin: event.target.value,
                }))
              }
              disabled={isPending}
            />
          </div>

          <div className="space-y-1">
            <label className="text-xs font-medium">WordPress wachtwoord</label>
            <Input
              type="password"
              placeholder="Application Password"
              value={addForm.wpPassword}
              onChange={(event) =>
                setAddForm((current) => ({
                  ...current,
                  wpPassword: event.target.value,
                }))
              }
              disabled={isPending}
            />
          </div>
        </div>

        <div className="flex justify-end">
          <Button
            onClick={addSite}
            disabled={
              isPending ||
              addForm.baseUrl.trim().length === 0 ||
              addForm.wpLogin.trim().length === 0 ||
              addForm.wpPassword.trim().length === 0
            }
          >
            {isPending ? "Toevoegen..." : "Site toevoegen"}
          </Button>
        </div>
      </SettingsSection>
    </div>
  )
}
