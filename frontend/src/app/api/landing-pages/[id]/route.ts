import { NextRequest, NextResponse } from "next/server"

import {
  getAuthenticatedUserId,
  getBackendApiUrl,
  readBackendError,
} from "@/lib/backend-api"

type RouteContext = {
  params: Promise<{ id: string }>
}

export async function GET(_request: NextRequest, context: RouteContext) {
  const authorization = await getAuthenticatedUserId()
  if (!authorization) {
    return NextResponse.json({ error: "Niet ingelogd." }, { status: 401 })
  }

  try {
    const { id } = await context.params
    if (!id) {
      return NextResponse.json(
        { error: "Landing page id ontbreekt." },
        { status: 400 }
      )
    }

    const response = await fetch(
      `${getBackendApiUrl()}/api/landing-pages/${encodeURIComponent(id)}`,
      {
        headers: {
          Authorization: authorization,
        },
      }
    )

    if (!response.ok) {
      const error = await readBackendError(
        response,
        "Kon landing page niet ophalen."
      )
      return NextResponse.json({ error }, { status: response.status })
    }

    return NextResponse.json(await response.json())
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Interne serverfout."
    return NextResponse.json(
      { error: `Kon landing page niet ophalen: ${message}` },
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
        { error: "Landing page id ontbreekt." },
        { status: 400 }
      )
    }

    const payload = (await request.json().catch(() => null)) as {
      content?: unknown
      meta_title?: unknown
      meta_description?: unknown
      slug?: unknown
    } | null

    if (!payload || typeof payload !== "object") {
      return NextResponse.json({ error: "Ongeldige request body." }, { status: 400 })
    }

    const response = await fetch(
      `${getBackendApiUrl()}/api/landing-pages/${encodeURIComponent(id)}`,
      {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          Authorization: authorization,
        },
        body: JSON.stringify(payload),
      }
    )

    if (!response.ok) {
      const error = await readBackendError(
        response,
        "Kon landing page niet opslaan."
      )
      return NextResponse.json({ error }, { status: response.status })
    }

    const data = await response.json()
    return NextResponse.json({ landing_page: data })
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Interne serverfout."
    return NextResponse.json(
      { error: `Kon landing page niet opslaan: ${message}` },
      { status: 500 }
    )
  }
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
        { error: "Landing page id ontbreekt." },
        { status: 400 }
      )
    }

    const response = await fetch(
      `${getBackendApiUrl()}/api/landing-pages/${encodeURIComponent(id)}`,
      {
        method: "DELETE",
        headers: {
          Authorization: authorization,
        },
      }
    )

    if (!response.ok) {
      const error = await readBackendError(
        response,
        "Kon landing page niet verwijderen."
      )
      return NextResponse.json({ error }, { status: response.status })
    }

    return NextResponse.json({ ok: true })
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Interne serverfout."
    return NextResponse.json(
      { error: `Kon landing page niet verwijderen: ${message}` },
      { status: 500 }
    )
  }
}
