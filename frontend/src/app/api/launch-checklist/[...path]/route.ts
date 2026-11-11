import { NextRequest, NextResponse } from "next/server"

import {
  getAuthenticatedUserId,
  getBackendApiUrl,
  readBackendError,
} from "@/lib/backend-api"

type RouteContext = {
  params: Promise<{ path: string[] }>
}

const SEGMENT_PATTERN = /^[A-Za-z0-9_-]+$/

async function proxy(request: NextRequest, context: RouteContext, method: string) {
  const userId = await getAuthenticatedUserId()
  if (!userId) {
    return NextResponse.json({ error: "Niet ingelogd." }, { status: 401 })
  }

  const { path } = await context.params
  if (!path?.length || !path.every((segment) => SEGMENT_PATTERN.test(segment))) {
    return NextResponse.json({ error: "Ongeldig pad." }, { status: 400 })
  }

  const backendUrl = getBackendApiUrl()
  const search = request.nextUrl.search
  const target = `${backendUrl}/api/launch-checklist/${path.join("/")}${search}`

  const headers: Record<string, string> = { Authorization: userId }
  let body: string | undefined
  if (method === "POST" || method === "PATCH") {
    body = await request.text()
    headers["Content-Type"] = "application/json"
  }

  try {
    const response = await fetch(target, { method, headers, body, cache: "no-store" })

    if (!response.ok) {
      const error = await readBackendError(response, "Verzoek aan de backend is mislukt.")
      return NextResponse.json({ error }, { status: response.status })
    }

    const contentType = response.headers.get("content-type") ?? ""
    if (contentType.includes("text/csv")) {
      return new NextResponse(response.body, {
        status: 200,
        headers: {
          "Content-Type": contentType,
          "Content-Disposition":
            response.headers.get("content-disposition") ?? 'attachment; filename="export.csv"',
        },
      })
    }

    const payload = await response.json()
    return NextResponse.json(payload)
  } catch (error) {
    const details = error instanceof Error ? error.message : "Backend verbinding mislukt."
    return NextResponse.json(
      { error: `Backend niet bereikbaar (${backendUrl}). Details: ${details}` },
      { status: 502 }
    )
  }
}

export async function GET(request: NextRequest, context: RouteContext) {
  return proxy(request, context, "GET")
}

export async function POST(request: NextRequest, context: RouteContext) {
  return proxy(request, context, "POST")
}

export async function PATCH(request: NextRequest, context: RouteContext) {
  return proxy(request, context, "PATCH")
}

export async function DELETE(request: NextRequest, context: RouteContext) {
  return proxy(request, context, "DELETE")
}
