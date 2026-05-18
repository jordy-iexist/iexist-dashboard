"use client"

import { useCallback, useEffect, useMemo, useState, useTransition } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  CustomerWebsite,
  MetaPageItem,
  MetaRun,
  StartMetaRunResponse,
} from "@/lib/seo-types"

type WebsitesResponse =
  | {
      websites: CustomerWebsite[]
    }
  | {
      error: string
    }

type MetaLatestResponse =
  | {
      run: MetaRun | null
      pages: MetaPageItem[]
    }
  | {
      error: string
    }

type MetaRunResponse = MetaRun | { error: string }
type MetaRunPagesResponse =
  | {
      pages: MetaPageItem[]
      total: number
    }
  | {
      error: string
    }

type MetaStartRunResponse = StartMetaRunResponse | { error: string }
type MetaPageResponse = MetaPageItem | { error: string }

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

function shortText(value: string | null, maxLength = 100) {
  if (!value) {
    return "-"
  }
  const normalized = value.trim()
  if (normalized.length <= maxLength) {
    return normalized
  }
  return `${normalized.slice(0, maxLength).trimEnd()}...`
}

export function SeoMetaOptimizer() {
  const [websites, setWebsites] = useState<CustomerWebsite[]>([])
  const [selectedWebsiteId, setSelectedWebsiteId] = useState<string | null>(null)
  const [metaRun, setMetaRun] = useState<MetaRun | null>(null)
  const [metaPages, setMetaPages] = useState<MetaPageItem[]>([])
  const [activeMetaRunId, setActiveMetaRunId] = useState<string | null>(null)
  const [pageLimitInput, setPageLimitInput] = useState("50")
  const [isLoadingWebsites, setIsLoadingWebsites] = useState(true)
  const [isLoadingMeta, setIsLoadingMeta] = useState(false)
  const [feedback, setFeedback] = useState<{
    type: "success" | "error" | null
    message: string
  }>({ type: null, message: "" })
  const [isPending, startTransition] = useTransition()

  const selectedWebsite = useMemo(
    () => websites.find((website) => website.id === selectedWebsiteId) ?? null,
    [websites, selectedWebsiteId]
  )

  const isMetaRunRunning =
    metaRun?.status === "pending" || metaRun?.status === "processing"

  const pendingReviewCount = useMemo(
    () => metaPages.filter((item) => item.review_status === "pending_review").length,
    [metaPages]
  )

  const approvedCount = useMemo(
    () => metaPages.filter((item) => item.review_status === "approved").length,
    [metaPages]
  )

  const rejectedCount = useMemo(
    () => metaPages.filter((item) => item.review_status === "rejected").length,
    [metaPages]
  )

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

  const loadMetaLatest = useCallback(async (websiteId: string) => {
    setIsLoadingMeta(true)
    try {
      const response = await fetch(
        `/api/seo/websites/${encodeURIComponent(websiteId)}/meta-latest?pages_limit=200`,
        {
          method: "GET",
          cache: "no-store",
        }
      )
      const payload = (await response.json().catch(() => null)) as
        | MetaLatestResponse
        | null
      if (!response.ok) {
        throw new Error(
          getErrorMessage(payload, "Kon meta overzicht niet ophalen.")
        )
      }

      const nextRun =
        payload && "run" in payload && payload.run ? payload.run : null
      const nextPages =
        payload && "pages" in payload && Array.isArray(payload.pages)
          ? payload.pages
          : []

      setMetaRun(nextRun)
      setMetaPages(nextPages)

      if (
        nextRun &&
        (nextRun.status === "pending" || nextRun.status === "processing")
      ) {
        setActiveMetaRunId(nextRun.id)
      } else {
        setActiveMetaRunId(null)
      }
    } catch (error) {
      setFeedback({
        type: "error",
        message:
          error instanceof Error
            ? error.message
            : "Kon meta overzicht niet ophalen.",
      })
    } finally {
      setIsLoadingMeta(false)
    }
  }, [])

  useEffect(() => {
    loadWebsites()
  }, [loadWebsites])

  useEffect(() => {
    if (websites.length === 0) {
      setSelectedWebsiteId(null)
      setMetaRun(null)
      setMetaPages([])
      setActiveMetaRunId(null)
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
    loadMetaLatest(selectedWebsiteId)
  }, [selectedWebsiteId, loadMetaLatest])

  useEffect(() => {
    if (!activeMetaRunId || !selectedWebsiteId) {
      return
    }

    let isCancelled = false
    const poll = async () => {
      try {
        const [runResponse, pagesResponse] = await Promise.all([
          fetch(`/api/seo/meta-runs/${encodeURIComponent(activeMetaRunId)}`, {
            method: "GET",
            cache: "no-store",
          }),
          fetch(
            `/api/seo/meta-runs/${encodeURIComponent(
              activeMetaRunId
            )}/pages?limit=200&offset=0`,
            {
              method: "GET",
              cache: "no-store",
            }
          ),
        ])

        const runPayload = (await runResponse.json().catch(() => null)) as
          | MetaRunResponse
          | null
        const pagesPayload = (await pagesResponse.json().catch(() => null)) as
          | MetaRunPagesResponse
          | null

        if (!runResponse.ok) {
          throw new Error(getErrorMessage(runPayload, "Kon meta run niet ophalen."))
        }
        if (!pagesResponse.ok) {
          throw new Error(
            getErrorMessage(pagesPayload, "Kon meta pagina's niet ophalen.")
          )
        }
        if (!runPayload || !("id" in runPayload)) {
          throw new Error("Onverwachte meta run response.")
        }
        if (!pagesPayload || !("pages" in pagesPayload)) {
          throw new Error("Onverwachte meta pages response.")
        }
        if (isCancelled) {
          return
        }

        setMetaRun(runPayload)
        setMetaPages(pagesPayload.pages)
        if (
          runPayload.status === "completed" ||
          runPayload.status === "failed" ||
          runPayload.status === "canceled"
        ) {
          setActiveMetaRunId(null)
          await loadMetaLatest(selectedWebsiteId)
        }
      } catch (error) {
        if (!isCancelled) {
          setFeedback({
            type: "error",
            message:
              error instanceof Error
                ? error.message
                : "Kon meta run status niet ophalen.",
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
  }, [activeMetaRunId, loadMetaLatest, selectedWebsiteId])

  const startMetaRun = () => {
    if (!selectedWebsiteId) {
      return
    }

    const parsedLimit = Number.parseInt(pageLimitInput.trim(), 10)
    const pageLimit =
      Number.isFinite(parsedLimit) && parsedLimit > 0 ? parsedLimit : 50

    setFeedback({ type: null, message: "" })
    startTransition(async () => {
      try {
        const response = await fetch(
          `/api/seo/websites/${encodeURIComponent(selectedWebsiteId)}/meta-runs`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
            },
            body: JSON.stringify({
              page_limit: pageLimit,
            }),
          }
        )
        const payload = (await response.json().catch(() => null)) as
          | MetaStartRunResponse
          | null
        if (!response.ok) {
          throw new Error(getErrorMessage(payload, "Kon meta run niet starten."))
        }
        if (!payload || !("run_id" in payload)) {
          throw new Error("Onverwachte start response.")
        }

        setActiveMetaRunId(payload.run_id)
        setFeedback({
          type: "success",
          message: "Meta run gestart.",
        })
        await loadMetaLatest(selectedWebsiteId)
      } catch (error) {
        setFeedback({
          type: "error",
          message:
            error instanceof Error ? error.message : "Kon meta run niet starten.",
        })
      }
    })
  }

  const updateMetaPage = (
    pageId: string,
    body: {
      review_status?: "pending_review" | "approved" | "rejected"
      approved_title?: string
      approved_description?: string
    }
  ) => {
    if (!selectedWebsiteId) {
      return
    }
    setFeedback({ type: null, message: "" })
    startTransition(async () => {
      try {
        const response = await fetch(`/api/seo/meta-pages/${encodeURIComponent(pageId)}`, {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify(body),
        })
        const payload = (await response.json().catch(() => null)) as
          | MetaPageResponse
          | null
        if (!response.ok) {
          throw new Error(
            getErrorMessage(payload, "Kon meta pagina niet bijwerken.")
          )
        }
        await loadMetaLatest(selectedWebsiteId)
      } catch (error) {
        setFeedback({
          type: "error",
          message:
            error instanceof Error
              ? error.message
              : "Kon meta pagina niet bijwerken.",
        })
      }
    })
  }

  const approveWithEdit = (page: MetaPageItem) => {
    const initialTitle = page.approved_title ?? page.suggested_title ?? ""
    const initialDescription =
      page.approved_description ?? page.suggested_description ?? ""

    const title = window.prompt("Approved meta title", initialTitle)
    if (title === null) {
      return
    }
    const description = window.prompt("Approved meta description", initialDescription)
    if (description === null) {
      return
    }
    updateMetaPage(page.id, {
      review_status: "approved",
      approved_title: title,
      approved_description: description,
    })
  }

  return (
    <div className="space-y-4 rounded-lg border p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Meta Optimizer</h2>
          <p className="text-sm text-muted-foreground">
            Genereer en review meta titles/descriptions per websitepagina.
          </p>
        </div>
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

      <div className="grid gap-3 md:grid-cols-[2fr_1fr_1fr]">
        <select
          value={selectedWebsiteId ?? ""}
          onChange={(event) => setSelectedWebsiteId(event.target.value)}
          disabled={isPending || isLoadingWebsites || websites.length === 0}
          className="w-full rounded-md border bg-background px-3 py-2 text-sm"
        >
          {websites.length === 0 ? (
            <option value="">Geen websites beschikbaar</option>
          ) : (
            websites.map((website) => (
              <option key={website.id} value={website.id}>
                {website.name} ({website.domain})
              </option>
            ))
          )}
        </select>
        <Input
          value={pageLimitInput}
          onChange={(event) => setPageLimitInput(event.target.value)}
          placeholder="Pagina limiet"
          inputMode="numeric"
          disabled={isPending}
        />
        <Button
          onClick={startMetaRun}
          disabled={isPending || !selectedWebsite || isMetaRunRunning}
        >
          {isMetaRunRunning ? "Meta run bezig..." : "Start meta run"}
        </Button>
      </div>

      {selectedWebsite && (
        <p className="text-xs text-muted-foreground">
          Actieve website: {selectedWebsite.base_url}
        </p>
      )}

      {metaRun ? (
        <div className="rounded-md border bg-muted/20 p-3 text-sm space-y-1">
          <p>
            Status: <strong>{metaRun.status}</strong>
          </p>
          <p>
            Verwerkt: {metaRun.processed_pages}/{metaRun.total_pages}
          </p>
          <p>
            Review: {pendingReviewCount} pending, {approvedCount} approved,{" "}
            {rejectedCount} rejected
          </p>
          {metaRun.failed_pages > 0 && (
            <p className="text-amber-600">Mislukte pagina&apos;s: {metaRun.failed_pages}</p>
          )}
          {metaRun.skipped_due_to_limit > 0 && (
            <p className="text-amber-600">
              Overgeslagen door limiet: {metaRun.skipped_due_to_limit}
            </p>
          )}
          {metaRun.error_message && <p className="text-red-600">{metaRun.error_message}</p>}
          <p className="text-xs text-muted-foreground">
            Laatste update: {formatDate(metaRun.updated_at)}
          </p>
        </div>
      ) : isLoadingMeta ? (
        <p className="text-sm text-muted-foreground">Meta data laden...</p>
      ) : (
        <p className="text-sm text-muted-foreground">
          Nog geen meta run voor deze website.
        </p>
      )}

      {metaPages.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          Geen pagina&apos;s beschikbaar. Start een meta run.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-muted-foreground">
                <th className="py-2 pr-2 font-medium">Pagina</th>
                <th className="py-2 pr-2 font-medium">Huidig</th>
                <th className="py-2 pr-2 font-medium">Voorstel</th>
                <th className="py-2 pr-2 font-medium">Status</th>
                <th className="py-2 pr-2 font-medium">Acties</th>
              </tr>
            </thead>
            <tbody>
              {metaPages.map((page) => (
                <tr key={page.id} className="border-b align-top last:border-0">
                  <td className="py-2 pr-2">
                    <a
                      href={page.url}
                      target="_blank"
                      rel="noreferrer noopener"
                      className="underline underline-offset-2"
                    >
                      {page.path}
                    </a>
                  </td>
                  <td className="py-2 pr-2">
                    <p className="font-medium">{shortText(page.current_title, 70)}</p>
                    <p className="text-xs text-muted-foreground">
                      {shortText(page.current_description, 110)}
                    </p>
                  </td>
                  <td className="py-2 pr-2">
                    <p className="font-medium">{shortText(page.suggested_title, 70)}</p>
                    <p className="text-xs text-muted-foreground">
                      {shortText(page.suggested_description, 110)}
                    </p>
                    {page.generation_error && (
                      <p className="mt-1 text-xs text-red-600">{page.generation_error}</p>
                    )}
                  </td>
                  <td className="py-2 pr-2">
                    <p>{page.review_status}</p>
                    {page.reviewed_at && (
                      <p className="text-xs text-muted-foreground">
                        {formatDate(page.reviewed_at)}
                      </p>
                    )}
                  </td>
                  <td className="py-2 pr-2">
                    <div className="flex flex-wrap gap-1">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() =>
                          updateMetaPage(page.id, {
                            review_status: "approved",
                          })
                        }
                        disabled={
                          isPending ||
                          (!page.suggested_title && !page.approved_title) ||
                          (!page.suggested_description && !page.approved_description)
                        }
                      >
                        Approve
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => approveWithEdit(page)}
                        disabled={isPending}
                      >
                        Bewerk + approve
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() =>
                          updateMetaPage(page.id, {
                            review_status: "rejected",
                          })
                        }
                        disabled={isPending}
                      >
                        Reject
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
