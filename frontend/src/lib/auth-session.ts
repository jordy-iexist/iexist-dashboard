import { cookies } from "next/headers"
import { type NextResponse } from "next/server"

export const ACCESS_TOKEN_COOKIE_NAME = "access_token"

export async function getAccessToken(): Promise<string | null> {
  const cookieStore = await cookies()
  const token = cookieStore.get(ACCESS_TOKEN_COOKIE_NAME)?.value
  if (!token || token.trim().length === 0) {
    return null
  }
  return token
}

export function setAccessTokenCookie(
  response: NextResponse,
  accessToken: string
) {
  response.cookies.set(ACCESS_TOKEN_COOKIE_NAME, accessToken, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 60 * 60 * 24,
  })
}

export function clearAccessTokenCookie(response: NextResponse) {
  response.cookies.set(ACCESS_TOKEN_COOKIE_NAME, "", {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 0,
  })
}
