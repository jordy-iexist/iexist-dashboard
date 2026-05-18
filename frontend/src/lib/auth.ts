import { cache } from "react"

import { type AuthUser } from "@/lib/auth-types"
import { getBackendApiUrl } from "@/lib/backend-api"
import { getAccessToken } from "@/lib/auth-session"

function readUserFromPayload(payload: unknown): AuthUser | null {
  if (!payload || typeof payload !== "object") {
    return null
  }

  const direct = payload as Partial<AuthUser>
  if (typeof direct.id === "string" && typeof direct.email === "string") {
    return {
      id: direct.id,
      email: direct.email,
      created_at:
        typeof direct.created_at === "string" ? direct.created_at : null,
    }
  }

  const nested = (payload as { user?: unknown }).user
  if (!nested || typeof nested !== "object") {
    return null
  }

  const user = nested as Partial<AuthUser>
  if (typeof user.id !== "string" || typeof user.email !== "string") {
    return null
  }

  return {
    id: user.id,
    email: user.email,
    created_at: typeof user.created_at === "string" ? user.created_at : null,
  }
}

export const getCurrentUser = cache(async (): Promise<AuthUser | null> => {
  const accessToken = await getAccessToken()
  if (!accessToken) {
    return null
  }

  try {
    const response = await fetch(`${getBackendApiUrl()}/api/auth/me`, {
      method: "GET",
      headers: {
        Authorization: `Bearer ${accessToken}`,
      },
      cache: "no-store",
    })

    if (!response.ok) {
      return null
    }

    return readUserFromPayload(await response.json().catch(() => null))
  } catch {
    return null
  }
})
