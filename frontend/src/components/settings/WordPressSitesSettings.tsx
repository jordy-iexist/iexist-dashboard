"use client"

import { useCallback, useEffect, useMemo, useState, useTransition } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
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
    <section className="rounded-lg border p-6 space-y-5">
      <div className="space-y-1">
        <h2 className="text-lg font-semibold">WordPress Sites</h2>
        <p className="text-sm text-muted-foreground">
          Voeg zelf WordPress sites toe met URL, login en wachtwoord zodat het
          team blogs kan publiceren.
        </p>
      </div>

      {feedback.message && (
        <div
          className={`rounded-md border px-3 py-2 text-sm ${
            feedback.type === "success"
              ? "border-green-200 bg-green-50 text-green-700"
              : "border-red-200 bg-red-50 text-red-700"
          }`}
        >
          {feedback.message}
        </div>
      )}

      <div className="space-y-3 rounded-lg border bg-muted/20 p-4">
        <h3 className="text-sm font-semibold">Nieuwe site toevoegen</h3>
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
      </div>

      <div className="space-y-3">
        <h3 className="text-sm font-semibold">Gekoppelde sites</h3>

        {isLoading && (
          <p className="text-sm text-muted-foreground">WordPress sites laden...</p>
        )}

        {!isLoading && sortedSites.length === 0 && (
          <p className="text-sm text-muted-foreground">
            Nog geen WordPress sites gekoppeld.
          </p>
        )}

        {!isLoading &&
          sortedSites.map((site) => {
            const isEditing = editingSiteId === site.id && editForm
            return (
              <article key={site.id} className="rounded-lg border p-4 space-y-3">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="space-y-1">
                    <p className="font-medium">{site.name}</p>
                    <p className="text-xs text-muted-foreground">
                      {site.base_url} · {site.wp_login}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      Toegevoegd: {formatDate(site.created_at)}
                    </p>
                  </div>

                  <div className="flex items-center gap-2">
                    <span
                      className={`rounded-full px-2.5 py-1 text-xs font-medium ${
                        site.is_active
                          ? "bg-green-100 text-green-700"
                          : "bg-zinc-200 text-zinc-700"
                      }`}
                    >
                      {site.is_active ? "Actief" : "Inactief"}
                    </span>
                    {!isEditing && (
                      <Button
                        variant="outline"
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
                  <div className="space-y-3 rounded-md border bg-muted/20 p-3">
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
              </article>
            )
          })}
      </div>
    </section>
  )
}
