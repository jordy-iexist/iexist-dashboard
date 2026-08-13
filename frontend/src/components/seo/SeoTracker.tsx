"use client"

import { useCallback, useEffect, useMemo, useState, useTransition } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  CustomerWebsite,
  SerpScan,
  StartWebsiteScanResponse,
  WebsiteKeyword,
  WebsiteRanking,
} from "@/lib/seo-types"

type WebsitesResponse =
  | {
      websites: CustomerWebsite[]
    }
  | {
      error: string
    }

type KeywordsResponse =
  | {
      keywords: WebsiteKeyword[]
    }
  | {
      error: string
    }

type RankingsResponse =
  | {
      website_id: string
      rankings: WebsiteRanking[]
    }
  | {
      error: string
    }

type ScansResponse =
  | {
      scans: SerpScan[]
    }
  | {
      error: string
    }

type ScanResponse = SerpScan | { error: string }
type StartScanResponse = StartWebsiteScanResponse | { error: string }
type CancelScanResponse = SerpScan | { error: string }
type WebsiteResponse = CustomerWebsite | { error: string }
type KeywordResponse = WebsiteKeyword | { error: string }
type DeleteResponse =
  | {
      status: string
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

function formatDate(value: string | null | undefined) {
  if (!value) {
    return "-"
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return "-"
  }
  return new Intl.DateTimeFormat("nl-NL", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date)
}

function formatPosition(position: number | null) {
  if (position === null) {
    return "Niet gevonden"
  }
  return String(position)
}

export function SeoTracker() {
  const [websites, setWebsites] = useState<CustomerWebsite[]>([])
  const [selectedWebsiteId, setSelectedWebsiteId] = useState<string | null>(null)
  const [keywords, setKeywords] = useState<WebsiteKeyword[]>([])
  const [rankings, setRankings] = useState<WebsiteRanking[]>([])
  const [latestScan, setLatestScan] = useState<SerpScan | null>(null)
  const [activeScanId, setActiveScanId] = useState<string | null>(null)
  const [isLoadingWebsites, setIsLoadingWebsites] = useState(true)
  const [isLoadingDetails, setIsLoadingDetails] = useState(false)
  const [websiteForm, setWebsiteForm] = useState({ name: "", baseUrl: "" })
  const [keywordInput, setKeywordInput] = useState("")
  const [feedback, setFeedback] = useState<{
    type: "success" | "error" | null
    message: string
  }>({ type: null, message: "" })
  const [isPending, startTransition] = useTransition()

  const selectedWebsite = useMemo(
    () => websites.find((website) => website.id === selectedWebsiteId) ?? null,
    [websites, selectedWebsiteId]
  )

  const activeKeywordsCount = useMemo(
    () => keywords.filter((keyword) => keyword.is_active).length,
    [keywords]
  )

  const isScanRunning =
    latestScan?.status === "pending" || latestScan?.status === "processing"

  const loadWebsites = useCallback(async () => {
    setIsLoadingWebsites(true)
    try {
      const response = await fetch("/api/seo/websites", {
        method: "GET",
        cache: "no-store",
      })
      const payload = (await response.json().catch(() => null)) as
        | WebsitesResponse
        | null
      if (!response.ok) {
        throw new Error(getErrorMessage(payload, "Kon websites niet ophalen."))
      }

      const nextWebsites =
        payload && "websites" in payload && Array.isArray(payload.websites)
          ? payload.websites
          : []
      setWebsites(nextWebsites)
    } catch (error) {
      setFeedback({
        type: "error",
        message:
          error instanceof Error ? error.message : "Kon websites niet ophalen.",
      })
    } finally {
      setIsLoadingWebsites(false)
    }
  }, [])

  const loadWebsiteDetails = useCallback(async (websiteId: string) => {
    setIsLoadingDetails(true)
    try {
      const [keywordsResponse, rankingsResponse, scansResponse] = await Promise.all([
        fetch(`/api/seo/websites/${encodeURIComponent(websiteId)}/keywords`, {
          method: "GET",
          cache: "no-store",
        }),
        fetch(`/api/seo/websites/${encodeURIComponent(websiteId)}/rankings`, {
          method: "GET",
          cache: "no-store",
        }),
        fetch(
          `/api/seo/websites/${encodeURIComponent(websiteId)}/scans?limit=1`,
          {
            method: "GET",
            cache: "no-store",
          }
        ),
      ])

      const keywordsPayload = (await keywordsResponse
        .json()
        .catch(() => null)) as KeywordsResponse | null
      if (!keywordsResponse.ok) {
        throw new Error(
          getErrorMessage(keywordsPayload, "Kon keywords niet ophalen.")
        )
      }

      const rankingsPayload = (await rankingsResponse
        .json()
        .catch(() => null)) as RankingsResponse | null
      if (!rankingsResponse.ok) {
        throw new Error(
          getErrorMessage(rankingsPayload, "Kon rankings niet ophalen.")
        )
      }

      const scansPayload = (await scansResponse
        .json()
        .catch(() => null)) as ScansResponse | null
      if (!scansResponse.ok) {
        throw new Error(getErrorMessage(scansPayload, "Kon scans niet ophalen."))
      }

      const nextKeywords =
        keywordsPayload &&
        "keywords" in keywordsPayload &&
        Array.isArray(keywordsPayload.keywords)
          ? keywordsPayload.keywords
          : []
      const nextRankings =
        rankingsPayload &&
        "rankings" in rankingsPayload &&
        Array.isArray(rankingsPayload.rankings)
          ? rankingsPayload.rankings
          : []
      const nextScans =
        scansPayload && "scans" in scansPayload && Array.isArray(scansPayload.scans)
          ? scansPayload.scans
          : []
      const nextLatestScan = nextScans[0] ?? null

      setKeywords(nextKeywords)
      setRankings(nextRankings)
      setLatestScan(nextLatestScan)
      if (
        nextLatestScan &&
        (nextLatestScan.status === "pending" ||
          nextLatestScan.status === "processing")
      ) {
        setActiveScanId(nextLatestScan.id)
      }
    } catch (error) {
      setFeedback({
        type: "error",
        message:
          error instanceof Error
            ? error.message
            : "Kon website details niet ophalen.",
      })
    } finally {
      setIsLoadingDetails(false)
    }
  }, [])

  useEffect(() => {
    loadWebsites()
  }, [loadWebsites])

  useEffect(() => {
    if (websites.length === 0) {
      setSelectedWebsiteId(null)
      setKeywords([])
      setRankings([])
      setLatestScan(null)
      setActiveScanId(null)
      return
    }

    if (!selectedWebsiteId || !websites.some((site) => site.id === selectedWebsiteId)) {
      setSelectedWebsiteId(websites[0].id)
    }
  }, [websites, selectedWebsiteId])

  useEffect(() => {
    if (!selectedWebsiteId) {
      return
    }
    loadWebsiteDetails(selectedWebsiteId)
  }, [selectedWebsiteId, loadWebsiteDetails])

  useEffect(() => {
    if (!activeScanId || !selectedWebsiteId) {
      return
    }

    let isCancelled = false
    const poll = async () => {
      try {
        const response = await fetch(
          `/api/seo/scans/${encodeURIComponent(activeScanId)}`,
          {
            method: "GET",
            cache: "no-store",
          }
        )
        const payload = (await response.json().catch(() => null)) as
          | ScanResponse
          | null
        if (!response.ok) {
          throw new Error(getErrorMessage(payload, "Kon scanstatus niet ophalen."))
        }
        if (!payload || !("id" in payload)) {
          throw new Error("Onverwachte scanstatus response.")
        }
        if (isCancelled) {
          return
        }

        setLatestScan(payload)
        if (
          payload.status === "completed" ||
          payload.status === "failed" ||
          payload.status === "canceled"
        ) {
          setActiveScanId(null)
          await loadWebsiteDetails(selectedWebsiteId)
        }
      } catch (error) {
        if (!isCancelled) {
          setFeedback({
            type: "error",
            message:
              error instanceof Error
                ? error.message
                : "Kon scanstatus niet ophalen.",
          })
        }
      }
    }

    poll()
    const timer = setInterval(poll, 3000)
    return () => {
      isCancelled = true
      clearInterval(timer)
    }
  }, [activeScanId, loadWebsiteDetails, selectedWebsiteId])

  const addWebsite = () => {
    setFeedback({ type: null, message: "" })
    startTransition(async () => {
      try {
        const response = await fetch("/api/seo/websites", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            name: websiteForm.name.trim(),
            base_url: websiteForm.baseUrl.trim(),
          }),
        })
        const payload = (await response.json().catch(() => null)) as
          | WebsiteResponse
          | null
        if (!response.ok) {
          throw new Error(getErrorMessage(payload, "Kon website niet toevoegen."))
        }
        if (!payload || !("id" in payload)) {
          throw new Error("Onverwachte website response.")
        }

        setWebsiteForm({ name: "", baseUrl: "" })
        setFeedback({
          type: "success",
          message: "Website is toegevoegd.",
        })
        await loadWebsites()
        setSelectedWebsiteId(payload.id)
      } catch (error) {
        setFeedback({
          type: "error",
          message:
            error instanceof Error ? error.message : "Kon website niet toevoegen.",
        })
      }
    })
  }

  const addKeyword = () => {
    if (!selectedWebsiteId) {
      return
    }
    setFeedback({ type: null, message: "" })
    startTransition(async () => {
      try {
        const response = await fetch(
          `/api/seo/websites/${encodeURIComponent(selectedWebsiteId)}/keywords`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
            },
            body: JSON.stringify({
              keyword: keywordInput,
            }),
          }
        )
        const payload = (await response.json().catch(() => null)) as
          | KeywordResponse
          | null
        if (!response.ok) {
          throw new Error(getErrorMessage(payload, "Kon keyword niet toevoegen."))
        }
        if (!payload || !("id" in payload)) {
          throw new Error("Onverwachte keyword response.")
        }

        setKeywordInput("")
        setFeedback({
          type: "success",
          message: "Keyword is toegevoegd.",
        })
        await loadWebsiteDetails(selectedWebsiteId)
      } catch (error) {
        setFeedback({
          type: "error",
          message:
            error instanceof Error ? error.message : "Kon keyword niet toevoegen.",
        })
      }
    })
  }

  const toggleKeywordActive = (keyword: WebsiteKeyword) => {
    setFeedback({ type: null, message: "" })
    startTransition(async () => {
      try {
        const response = await fetch(
          `/api/seo/keywords/${encodeURIComponent(keyword.id)}`,
          {
            method: "PATCH",
            headers: {
              "Content-Type": "application/json",
            },
            body: JSON.stringify({
              is_active: !keyword.is_active,
            }),
          }
        )
        const payload = (await response.json().catch(() => null)) as
          | KeywordResponse
          | null
        if (!response.ok) {
          throw new Error(getErrorMessage(payload, "Kon keyword niet bijwerken."))
        }
        if (!selectedWebsiteId) {
          return
        }
        await loadWebsiteDetails(selectedWebsiteId)
      } catch (error) {
        setFeedback({
          type: "error",
          message:
            error instanceof Error ? error.message : "Kon keyword niet bijwerken.",
        })
      }
    })
  }

  const startScan = () => {
    if (!selectedWebsiteId) {
      return
    }
    setFeedback({ type: null, message: "" })
    startTransition(async () => {
      try {
        const response = await fetch(
          `/api/seo/websites/${encodeURIComponent(selectedWebsiteId)}/scan`,
          {
            method: "POST",
          }
        )
        const payload = (await response.json().catch(() => null)) as
          | StartScanResponse
          | null
        if (!response.ok) {
          throw new Error(getErrorMessage(payload, "Kon scan niet starten."))
        }
        if (!payload || !("scan_id" in payload)) {
          throw new Error("Onverwachte scanstart response.")
        }

        setActiveScanId(payload.scan_id)
        setFeedback({
          type: "success",
          message: payload.truncated_by_limit
            ? `Scan gestart. ${payload.skipped_due_to_limit} keyword(s) overgeslagen door limiet (${payload.max_requests_per_scan} per scan).`
            : "Scan gestart.",
        })
      } catch (error) {
        setFeedback({
          type: "error",
          message: error instanceof Error ? error.message : "Kon scan niet starten.",
        })
      }
    })
  }

  const cancelScan = () => {
    const scanId = activeScanId ?? latestScan?.id ?? null
    if (!scanId) {
      return
    }
    setFeedback({ type: null, message: "" })
    startTransition(async () => {
      try {
        const response = await fetch(
          `/api/seo/scans/${encodeURIComponent(scanId)}/cancel`,
          {
            method: "POST",
          }
        )
        const payload = (await response.json().catch(() => null)) as
          | CancelScanResponse
          | null
        if (!response.ok) {
          throw new Error(getErrorMessage(payload, "Kon scan niet annuleren."))
        }
        if (!payload || !("id" in payload)) {
          throw new Error("Onverwachte cancel response.")
        }

        setLatestScan(payload)
        setActiveScanId(null)
        setFeedback({
          type: "success",
          message: "Scan is geannuleerd.",
        })
        if (selectedWebsiteId) {
          await loadWebsiteDetails(selectedWebsiteId)
        }
      } catch (error) {
        setFeedback({
          type: "error",
          message:
            error instanceof Error ? error.message : "Kon scan niet annuleren.",
        })
      }
    })
  }

  const deleteWebsite = () => {
    if (!selectedWebsite) {
      return
    }
    const confirmed = window.confirm(
      `Website "${selectedWebsite.name}" verwijderen? Alle keywords, scans en resultaten voor deze website worden ook verwijderd.`
    )
    if (!confirmed) {
      return
    }

    setFeedback({ type: null, message: "" })
    startTransition(async () => {
      try {
        const response = await fetch(
          `/api/seo/websites/${encodeURIComponent(selectedWebsite.id)}`,
          {
            method: "DELETE",
          }
        )
        const payload = (await response.json().catch(() => null)) as
          | DeleteResponse
          | null
        if (!response.ok) {
          throw new Error(getErrorMessage(payload, "Kon website niet verwijderen."))
        }

        setKeywords([])
        setRankings([])
        setLatestScan(null)
        setActiveScanId(null)
        setFeedback({
          type: "success",
          message: "Website is verwijderd.",
        })
        await loadWebsites()
      } catch (error) {
        setFeedback({
          type: "error",
          message:
            error instanceof Error
              ? error.message
              : "Kon website niet verwijderen.",
        })
      }
    })
  }

  const deleteKeyword = (keyword: WebsiteKeyword) => {
    const confirmed = window.confirm(
      `Keyword "${keyword.keyword}" verwijderen?`
    )
    if (!confirmed || !selectedWebsiteId) {
      return
    }

    setFeedback({ type: null, message: "" })
    startTransition(async () => {
      try {
        const response = await fetch(
          `/api/seo/keywords/${encodeURIComponent(keyword.id)}`,
          {
            method: "DELETE",
          }
        )
        const payload = (await response.json().catch(() => null)) as
          | DeleteResponse
          | null
        if (!response.ok) {
          throw new Error(getErrorMessage(payload, "Kon keyword niet verwijderen."))
        }

        setFeedback({
          type: "success",
          message: "Keyword is verwijderd.",
        })
        await loadWebsiteDetails(selectedWebsiteId)
      } catch (error) {
        setFeedback({
          type: "error",
          message:
            error instanceof Error
              ? error.message
              : "Kon keyword niet verwijderen.",
        })
      }
    })
  }

  return (
    <div className="space-y-6">
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

      <div className="grid gap-6 lg:grid-cols-3">
        <section className="space-y-4 lg:col-span-1">
          <div className="rounded-lg border p-4 space-y-3">
            <h2 className="text-sm font-semibold">Nieuwe website</h2>
            <Input
              placeholder="Naam (bijv. Klant A)"
              value={websiteForm.name}
              onChange={(event) =>
                setWebsiteForm((current) => ({
                  ...current,
                  name: event.target.value,
                }))
              }
              disabled={isPending}
            />
            <Input
              placeholder="https://voorbeeld.nl"
              value={websiteForm.baseUrl}
              onChange={(event) =>
                setWebsiteForm((current) => ({
                  ...current,
                  baseUrl: event.target.value,
                }))
              }
              disabled={isPending}
            />
            <Button
              onClick={addWebsite}
              disabled={
                isPending ||
                websiteForm.name.trim().length === 0 ||
                websiteForm.baseUrl.trim().length === 0
              }
              className="w-full"
            >
              Website toevoegen
            </Button>
          </div>

          <div className="rounded-lg border p-4 space-y-2">
            <h2 className="text-sm font-semibold">Websites</h2>
            {isLoadingWebsites ? (
              <p className="text-sm text-muted-foreground">Websites laden...</p>
            ) : websites.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Nog geen websites toegevoegd.
              </p>
            ) : (
              <div className="space-y-2">
                {websites.map((website) => (
                  <button
                    key={website.id}
                    type="button"
                    className={`w-full rounded-md border px-3 py-2 text-left text-sm transition-colors ${
                      website.id === selectedWebsiteId
                        ? "border-primary bg-primary/5"
                        : "hover:bg-muted/40"
                    }`}
                    onClick={() => setSelectedWebsiteId(website.id)}
                    disabled={isPending}
                  >
                    <p className="font-medium">{website.name}</p>
                    <p className="text-xs text-muted-foreground truncate">
                      {website.domain}
                    </p>
                  </button>
                ))}
              </div>
            )}
          </div>
        </section>

        <section className="space-y-4 lg:col-span-2">
          {!selectedWebsite ? (
            <div className="rounded-lg border p-6">
              <p className="text-sm text-muted-foreground">
                Selecteer eerst een website.
              </p>
            </div>
          ) : (
            <>
              <div className="rounded-lg border p-4 space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <h2 className="text-lg font-semibold">{selectedWebsite.name}</h2>
                    <p className="text-sm text-muted-foreground">
                      {selectedWebsite.base_url}
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Button
                      onClick={startScan}
                      disabled={isPending || isScanRunning || activeKeywordsCount === 0}
                    >
                      {isScanRunning ? "Scan bezig..." : "Scan nu"}
                    </Button>
                    {isScanRunning && (
                      <Button
                        onClick={cancelScan}
                        disabled={isPending}
                        variant="outline"
                      >
                        Scan stoppen
                      </Button>
                    )}
                    <Button
                      onClick={deleteWebsite}
                      disabled={isPending}
                      variant="destructive"
                    >
                      Website verwijderen
                    </Button>
                  </div>
                </div>

                {latestScan && (
                  <div className="rounded-md border bg-muted/20 p-3 text-sm space-y-1">
                    <p>
                      Status: <strong>{latestScan.status}</strong>
                    </p>
                    <p>
                      Verwerkt: {latestScan.processed_keywords}/
                      {latestScan.total_keywords}
                    </p>
                    {latestScan.failed_keywords > 0 && (
                      <p className="text-amber-600">
                        Mislukte keywords: {latestScan.failed_keywords}
                      </p>
                    )}
                    {latestScan.truncated_by_limit && (
                      <p className="text-amber-600">
                        Limiet actief: {latestScan.skipped_due_to_limit} keyword(s)
                        overgeslagen ({latestScan.max_requests_per_scan} per scan).
                      </p>
                    )}
                    {latestScan.error_message && (
                      <p className="text-red-600">{latestScan.error_message}</p>
                    )}
                    <p className="text-xs text-muted-foreground">
                      Laatste update: {formatDate(latestScan.updated_at)}
                    </p>
                  </div>
                )}
              </div>

              <div className="rounded-lg border p-4 space-y-3">
                <h3 className="text-sm font-semibold">Keywords</h3>
                <div className="flex gap-2">
                  <Input
                    placeholder="Voeg keyword toe"
                    value={keywordInput}
                    onChange={(event) => setKeywordInput(event.target.value)}
                    disabled={isPending}
                  />
                  <Button
                    onClick={addKeyword}
                    disabled={isPending || keywordInput.trim().length === 0}
                  >
                    Toevoegen
                  </Button>
                </div>

                {isLoadingDetails ? (
                  <p className="text-sm text-muted-foreground">Keywords laden...</p>
                ) : keywords.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    Nog geen keywords voor deze website.
                  </p>
                ) : (
                  <div className="space-y-2">
                    {keywords.map((keyword) => (
                      <div
                        key={keyword.id}
                        className="flex items-center justify-between rounded-md border px-3 py-2 text-sm"
                      >
                        <span>{keyword.keyword}</span>
                        <span className="inline-flex items-center gap-2">
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            onClick={() => deleteKeyword(keyword)}
                            disabled={isPending}
                          >
                            Verwijderen
                          </Button>
                          <span className="text-xs text-muted-foreground">
                            {keyword.is_active ? "Actief" : "Inactief"}
                          </span>
                          <input
                            type="checkbox"
                            checked={keyword.is_active}
                            onChange={() => toggleKeywordActive(keyword)}
                            disabled={isPending}
                          />
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="rounded-lg border p-4 space-y-3">
                <h3 className="text-sm font-semibold">Ranking overzicht</h3>
                {isLoadingDetails ? (
                  <p className="text-sm text-muted-foreground">Rankings laden...</p>
                ) : rankings.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    Nog geen ranking data. Start een scan.
                  </p>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b text-left text-muted-foreground">
                          <th className="py-2 pr-2 font-medium">Keyword</th>
                          <th className="py-2 pr-2 font-medium">Huidig</th>
                          <th className="py-2 pr-2 font-medium">Vorige</th>
                          <th className="py-2 pr-2 font-medium">Verschil</th>
                          <th className="py-2 pr-2 font-medium">Laatste scan</th>
                        </tr>
                      </thead>
                      <tbody>
                        {rankings.map((ranking) => (
                          <tr key={ranking.keyword_id} className="border-b last:border-0">
                            <td className="py-2 pr-2">
                              <div className="flex items-center gap-2">
                                <span>{ranking.keyword}</span>
                                {!ranking.is_active && (
                                  <span className="rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">
                                    Inactief
                                  </span>
                                )}
                              </div>
                            </td>
                            <td className="py-2 pr-2">
                              {formatPosition(ranking.current_position)}
                            </td>
                            <td className="py-2 pr-2">
                              {formatPosition(ranking.previous_position)}
                            </td>
                            <td className="py-2 pr-2">
                              {ranking.delta === null ? (
                                "-"
                              ) : (
                                <span
                                  className={
                                    ranking.delta > 0
                                      ? "text-green-600"
                                      : ranking.delta < 0
                                      ? "text-red-600"
                                      : ""
                                  }
                                >
                                  {ranking.delta > 0 ? `+${ranking.delta}` : ranking.delta}
                                </span>
                              )}
                            </td>
                            <td className="py-2 pr-2">
                              {formatDate(ranking.last_scanned_at)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  )
}
