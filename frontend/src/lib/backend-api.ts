import { getAccessToken } from "@/lib/auth-session"

export function getBackendApiUrl() {
  const url =
    process.env.BACKEND_API_URL ||
    process.env.NEXT_PUBLIC_API_URL ||
    "http://127.0.0.1:8000"

  return url.replace(/\/+$/, "")
}

export async function getBackendAuthorizationValue(): Promise<string | null> {
  const accessToken = await getAccessToken()
  if (!accessToken) {
    return null
  }

  return `Bearer ${accessToken}`
}

export async function getAuthenticatedUserId(): Promise<string | null> {
  return getBackendAuthorizationValue()
}

export async function readBackendError(
  response: Response,
  fallback: string
): Promise<string> {
  try {
    const payload = (await response.json()) as {
      detail?: unknown
      error?: unknown
      message?: unknown
    }
    const detail =
      typeof payload.detail === "string"
        ? payload.detail
        : typeof payload.error === "string"
        ? payload.error
        : typeof payload.message === "string"
        ? payload.message
        : null

    if (detail && detail.trim().length > 0) {
      return detail
    }
  } catch {
    // ignore JSON parse errors
  }

  try {
    const text = await response.text()
    if (text.trim().length > 0) {
      return text
    }
  } catch {
    // ignore body parse errors
  }

  return fallback
}
