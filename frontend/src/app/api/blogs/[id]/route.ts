import { NextRequest, NextResponse } from "next/server"

import {
  getAuthenticatedUserId,
  getBackendApiUrl,
  readBackendError,
} from "@/lib/backend-api"

type RouteContext = {
  params: Promise<{ id: string }>
}

export async function DELETE(_request: NextRequest, context: RouteContext) {
  const authorization = await getAuthenticatedUserId()
  if (!authorization) {
    return NextResponse.json({ error: "Niet ingelogd." }, { status: 401 })
  }

  try {
    const { id } = await context.params
    if (!id) {
      return NextResponse.json(
        { error: "Blog id ontbreekt." },
        { status: 400 }
      )
    }

    const response = await fetch(
      `${getBackendApiUrl()}/api/blogs/${encodeURIComponent(id)}`,
      {
        method: "DELETE",
        headers: {
          Authorization: authorization,
        },
      }
    )

    if (!response.ok) {
      const error = await readBackendError(response, "Kon blog niet verwijderen.")
      return NextResponse.json({ error }, { status: response.status })
    }

    return NextResponse.json({ ok: true })
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Interne serverfout."
    return NextResponse.json(
      { error: `Kon blog niet verwijderen: ${message}` },
      { status: 500 }
    )
  }
}

export async function PATCH(request: NextRequest, context: RouteContext) {
  const authorization = await getAuthenticatedUserId()
  if (!authorization) {
    return NextResponse.json({ error: "Niet ingelogd." }, { status: 401 })
  }

  try {
    const { id } = await context.params
    if (!id) {
      return NextResponse.json(
        { error: "Blog id ontbreekt." },
        { status: 400 }
      )
    }

    const payload = (await request.json().catch(() => null)) as
      | { content?: unknown }
      | null
    const rawContent = payload?.content
    const content = typeof rawContent === "string" ? rawContent.trim() : ""

    if (!content) {
      return NextResponse.json(
        { error: "Blog inhoud mag niet leeg zijn." },
        { status: 400 }
      )
    }

    const response = await fetch(
      `${getBackendApiUrl()}/api/blogs/${encodeURIComponent(id)}`,
      {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          Authorization: authorization,
        },
        body: JSON.stringify({ content }),
      }
    )

    if (!response.ok) {
      const error = await readBackendError(
        response,
        "Kon blog niet opslaan."
      )
      return NextResponse.json({ error }, { status: response.status })
    }

    return NextResponse.json({ blog: await response.json() })
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Interne serverfout."
    return NextResponse.json(
      { error: `Kon blog niet opslaan: ${message}` },
      { status: 500 }
    )
  }
}
